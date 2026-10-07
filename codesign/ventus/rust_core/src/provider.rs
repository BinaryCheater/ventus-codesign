//! Demand-driven integer/control execution for address-only instruction traces.
//! Encoding references: official Ventus LLVM 97df137 and Spike cd84209.
//! Unknown numerical payloads propagate as None; using them for control/address
//! returns an error, so data-dependent work cannot silently take a fabricated path.
use super::NumericMap;
use super::{
    Op, CONVERT, FADD, FCMP, FMA, FMAX, FMUL, FTOI, ITOF, LOAD, MMA_BF16, MMA_F16, MMA_TF32,
    PACKED, SCALAR, SFU, SHUFFLE, STORE, TENSOR, VECTOR,
};

fn sx(v: u32, bits: u32) -> u32 {
    ((v << (32 - bits)) as i32 >> (32 - bits)) as u32
}
fn required(v: Option<u32>, pc: u32) -> Result<u32, String> {
    v.ok_or_else(|| format!("numerical payload required for control/address at pc={pc:08x}"))
}
fn binary(a: Option<u32>, b: Option<u32>, f: impl FnOnce(u32, u32) -> u32) -> Option<u32> {
    Some(f(a?, b?))
}
fn cmp(a: u32, b: u32, f: u32) -> Result<bool, String> {
    Ok(match f {
        0 => a == b,
        1 => a != b,
        4 => (a as i32) < (b as i32),
        5 => (a as i32) >= (b as i32),
        6 => a < b,
        7 => a >= b,
        _ => return Err("unsupported branch".into()),
    })
}
fn integer(a: u32, b: u32, f: u32, top: u32) -> Result<u32, String> {
    Ok(match (f, top) {
        (0, 0) => a.wrapping_add(b),
        (0, 0x20) => a.wrapping_sub(b),
        (1, 0) => a.wrapping_shl(b & 31),
        (2, 0) => u32::from((a as i32) < (b as i32)),
        (3, 0) => u32::from(a < b),
        (4, 0) => a ^ b,
        (5, 0) => a.wrapping_shr(b & 31),
        (5, 0x20) => ((a as i32) >> (b & 31)) as u32,
        (6, 0) => a | b,
        (7, 0) => a & b,
        (0, 1) => a.wrapping_mul(b),
        (1, 1) => (((a as i32 as i64) * (b as i32 as i64)) >> 32) as u32,
        (2, 1) => (((a as i32 as i64) * (b as i64)) >> 32) as u32,
        (3, 1) => (((a as u64) * (b as u64)) >> 32) as u32,
        (4, 1) => {
            if b == 0 {
                u32::MAX
            } else {
                (a as i32).wrapping_div(b as i32) as u32
            }
        }
        (5, 1) => {
            if b == 0 {
                u32::MAX
            } else {
                a / b
            }
        }
        (6, 1) => {
            if b == 0 {
                a
            } else {
                (a as i32).wrapping_rem(b as i32) as u32
            }
        }
        (7, 1) => {
            if b == 0 {
                a
            } else {
                a % b
            }
        }
        _ => return Err("unsupported integer instruction".into()),
    })
}

// Value and per-bit validity; partial writes preserve other known bytes.
type Memory = NumericMap<u32, (u32, u32)>;
fn load(mem: &Memory, address: u32, width: usize, signed: bool) -> Option<u32> {
    let (value, known) = *mem.get(&(address & !3))?;
    let shift = (address & 3) * 8;
    let bits = (width * 8) as u32;
    let mask = if bits == 32 {
        u32::MAX
    } else {
        ((1u32 << bits) - 1) << shift
    };
    if known & mask != mask {
        return None;
    }
    let value = (value & mask) >> shift;
    Some(if signed && bits < 32 {
        sx(value, bits)
    } else {
        value
    })
}
fn store(mem: &mut Memory, address: u32, width: usize, value: Option<u32>) {
    let base = address & !3;
    let shift = (address & 3) * 8;
    let mask = if width == 4 {
        u32::MAX
    } else {
        ((1u32 << (width * 8)) - 1) << shift
    };
    let (old, valid) = mem.get(&base).copied().unwrap_or((0, 0));
    mem.insert(
        base,
        (
            (old & !mask) | ((value.unwrap_or(0) << shift) & mask),
            (valid & !mask) | if value.is_some() { mask } else { 0 },
        ),
    );
}
struct Join {
    pc: u32,
    second: u32,
    mask: u64,
    parent: u64,
    first: bool,
}

pub(super) fn generate(words: &[u32], launch: &[u64]) -> Result<Vec<Op>, String> {
    if launch.len() < 20 {
        return Err("truncated launch description".into());
    }
    let q =
        |i: usize| u32::try_from(launch[i]).map_err(|_| "launch value exceeds RV32".to_string());
    let base = q(0)?;
    let entry = q(1)?;
    let exit = q(2)?;
    let blocks = q(3)?;
    let wpb = q(4)?;
    let nt = q(5)?;
    if !(1..=32).contains(&nt) || wpb == 0 || blocks == 0 {
        return Err("invalid launch dimensions".into());
    }
    let init = launch[19] as usize;
    if launch.len() < 20 + 2 * init {
        return Err("invalid launch memory".into());
    }
    let mut initial = Memory::default();
    for i in 0..init {
        initial.insert(q(20 + 2 * i)?, (q(21 + 2 * i)?, u32::MAX));
    }
    let private_size = launch.get(20 + 2 * init).copied().unwrap_or(0) as u32;
    let mut ops = Vec::new();
    for block in q(16)?..q(16)? + blocks {
        for warp in 0..wpb {
            let mut x = [None; 256];
            x[0] = Some(0);
            x[1] = Some(exit);
            x[2] = Some(0x70000000);
            x[3] = Some(q(17)?);
            x[4] = Some(0);
            x[8] = x[2];
            x[10] = Some(q(9)?);
            let mut v = vec![[None; 32]; 256];
            let mut mem = initial.clone();
            let mut mask = (1u64 << nt) - 1;
            let mut vl = nt;
            let mut pc = entry;
            let mut ext = 0u32;
            let mut exti = false;
            let mut rpc = 0;
            let mut stack: Vec<Join> = Vec::new();
            let mut steps = 0;
            while pc != exit {
                steps += 1;
                if steps > 5_000_000 {
                    return Err(format!("dynamic instruction limit at {pc:08x}"));
                }
                let offset = pc.checked_sub(base).ok_or("PC below executable segment")?;
                if offset % 4 != 0 {
                    return Err("compressed instructions not supported".into());
                }
                let word = *words
                    .get(offset as usize / 4)
                    .ok_or_else(|| format!("PC outside executable segment: {pc:08x}"))?;
                if word & 3 != 3 && ![0x72, 0x0a, 0x2a, 0x5a, 0x7a, 0x42].contains(&(word & 127)) {
                    return Err(format!("compressed instruction at {pc:08x}"));
                }
                let opcode = word & 127;
                let f = (word >> 12) & 7;
                let top = word >> 25;
                let fun = word >> 26;
                let rd = ((word >> 7) & 31) + 32 * (ext & 7);
                let r1 = ((word >> 15) & 31) + 32 * (if exti { 0 } else { (ext >> 3) & 7 });
                let r2 = ((word >> 20) & 31) + 32 * ((ext >> (if exti { 3 } else { 6 })) & 7);
                let rd = rd as usize;
                let r1 = r1 as usize;
                let r2 = r2 as usize;
                let imm = sx(word >> 20, 12);
                let simm = sx(((word >> 25) << 5) | ((word >> 7) & 31), 12);
                let bi = sx(
                    ((word >> 31) << 12)
                        | (((word >> 7) & 1) << 11)
                        | (((word >> 25) & 63) << 5)
                        | (((word >> 8) & 15) << 1),
                    13,
                );
                let active_mask = mask & ((1u64 << vl) - 1);
                let mut next = pc.wrapping_add(4);
                let mut kind = SCALAR;
                let mut sources = Vec::new();
                let mut dest = None;
                let mut addresses = Vec::new();
                let mut width = 4usize;
                let mut extra_dests = Vec::new();
                let active = |i: usize| i < (vl as usize) && mask & (1 << i) != 0;
                match opcode {
                    0x37 => {
                        x[rd] = Some(word & 0xfffff000);
                        dest = Some(256 + rd);
                    }
                    0x17 => {
                        x[rd] = Some(pc.wrapping_add(word & 0xfffff000));
                        dest = Some(256 + rd);
                    }
                    0x13 => {
                        sources.push(256 + r1);
                        dest = Some(256 + rd);
                        let operand = if f == 1 || f == 5 {
                            Some((word >> 20) & 31)
                        } else {
                            Some(imm)
                        };
                        let t = if f == 5 { top } else { 0 };
                        x[rd] = match (x[r1], operand) {
                            (Some(a), Some(b)) => Some(integer(a, b, f, t)?),
                            _ => None,
                        };
                    }
                    0x33 => {
                        sources.extend([256 + r1, 256 + r2]);
                        dest = Some(256 + rd);
                        x[rd] = match (x[r1], x[r2]) {
                            (Some(a), Some(b)) => Some(integer(a, b, f, top)?),
                            _ => None,
                        };
                    }
                    0x63 => {
                        sources.extend([256 + r1, 256 + r2]);
                        if cmp(required(x[r1], pc)?, required(x[r2], pc)?, f)? {
                            next = pc.wrapping_add(bi);
                        }
                    }
                    0x6f => {
                        let j = sx(
                            ((word >> 31) << 20)
                                | (((word >> 12) & 255) << 12)
                                | (((word >> 20) & 1) << 11)
                                | (((word >> 21) & 1023) << 1),
                            21,
                        );
                        x[rd] = Some(next);
                        dest = Some(256 + rd);
                        next = pc.wrapping_add(j);
                    }
                    0x67 => {
                        sources.push(256 + r1);
                        let target = required(x[r1], pc)?.wrapping_add(imm) & !1;
                        x[rd] = Some(next);
                        dest = Some(256 + rd);
                        next = target;
                    }
                    0x03 | 0x23 => {
                        width = match f {
                            0 | 4 => 1,
                            1 | 5 => 2,
                            2 => 4,
                            _ => return Err(format!("scalar width not supported at {pc:08x}")),
                        };
                        sources.push(256 + r1);
                        let a = required(x[r1], pc)?.wrapping_add(if opcode == 0x03 {
                            imm
                        } else {
                            simm
                        });
                        addresses.push(a as u64);
                        if opcode == 0x03 {
                            kind = LOAD;
                            dest = Some(256 + rd);
                            x[rd] = load(&mem, a, width, f < 4);
                        } else {
                            kind = STORE;
                            sources.push(256 + r2);
                            store(&mut mem, a, width, x[r2]);
                        }
                    }
                    0x72 => {
                        kind = VECTOR;
                        sources.push(256 + r1);
                        dest = Some(rd);
                        let csr = word >> 20;
                        let lx = q(13)?;
                        let ly = q(14)?;
                        let gx = q(10)?.div_ceil(lx);
                        let gy = q(11)?.div_ceil(ly);
                        for i in 0..nt as usize {
                            if active(i) {
                                let local = warp * nt + i as u32;
                                let ids = [local % lx, (local / lx) % ly, local / (lx * ly)];
                                let gids = [
                                    (block % gx) * lx + ids[0],
                                    ((block / gx) % gy) * ly + ids[1],
                                    (block / (gx * gy)) * q(15)? + ids[2],
                                ];
                                v[rd][i] = Some(match csr {
                                    0x80d..=0x80f => gids[(csr - 0x80d) as usize],
                                    0x810 => gids[0] + q(10)? * (gids[1] + q(11)? * gids[2]),
                                    0x811..=0x813 => ids[(csr - 0x811) as usize],
                                    _ => {
                                        return Err(format!(
                                            "unsupported vector CSR {csr:03x} at {pc:08x}"
                                        ))
                                    }
                                });
                            }
                        }
                    }
                    0x73 => {
                        let csr = word >> 20;
                        if f == 0 {
                            return Err(format!("unsupported system instruction at {pc:08x}"));
                        }
                        let val = match csr {
                            0x800 => warp * nt,
                            0x801 => wpb,
                            0x802 => nt,
                            0x803 => q(18)?,
                            0x804 => block,
                            0x805 => warp,
                            0x806 => 0x70000000,
                            0x807 => 0x60000000 + block * wpb * nt * private_size,
                            0x808 => block % (q(10)?.div_ceil(q(13)?)),
                            0x809 => (block / q(10)?.div_ceil(q(13)?)) % q(11)?.div_ceil(q(14)?),
                            0x80a => block / (q(10)?.div_ceil(q(13)?) * q(11)?.div_ceil(q(14)?)),
                            0x80c => rpc,
                            0x300 | 0x305 | 0xc20 | 0xc21 => 0,
                            _ => return Err(format!("unsupported CSR {csr:03x} at {pc:08x}")),
                        };
                        x[rd] = Some(val);
                        dest = Some(256 + rd);
                        if f < 5 {
                            sources.push(256 + r1);
                        }
                    }
                    0x0b if f == 2 || f == 3 => {
                        ext = word >> 20;
                        exti = f == 3;
                    }
                    0x0b if f == 4 && top == 0 => {
                        break;
                    }
                    0x0b if f == 4 && top == 2 => {
                        return Err("collective barrier dynamic provider pending".into());
                    }
                    0x0b if f == 0 || f == 1 => {
                        kind = VECTOR;
                        sources.push(r1);
                        dest = Some(rd);
                        for i in 0..nt as usize {
                            if active(i) {
                                v[rd][i] = v[r1][i].map(|a| {
                                    if f == 0 {
                                        a.wrapping_add(imm)
                                    } else {
                                        a.wrapping_sub(imm)
                                    }
                                });
                            }
                        }
                    }
                    0x0b if f == 4 && fun == 3 => {
                        kind = TENSOR;
                        sources.extend([r1, r2, rd]);
                        dest = Some(rd);
                        for i in 0..nt as usize {
                            if active(i) {
                                v[rd][i] = None;
                            }
                        }
                    }
                    0x5b if f == 3 => {
                        sources.push(256 + r1);
                        dest = Some(256 + rd);
                        rpc = required(x[r1], pc)?.wrapping_add(imm);
                        x[rd] = Some(rpc);
                    }
                    0x5b if f == 2 => {
                        if let Some(j) = stack.last_mut() {
                            if j.pc == pc {
                                if j.first {
                                    j.first = false;
                                    mask = j.mask;
                                    next = j.second;
                                } else {
                                    mask = j.parent;
                                    stack.pop();
                                }
                            }
                        }
                    }
                    0x5b => {
                        kind = VECTOR;
                        sources.extend([r1, r2]);
                        let mut taken = 0;
                        for i in 0..nt as usize {
                            if active(i)
                                && cmp(required(v[r2][i], pc)?, required(v[r1][i], pc)?, f)?
                            {
                                taken |= 1 << i;
                            }
                        }
                        if taken == mask {
                            next = pc.wrapping_add(bi);
                        } else if taken != 0 {
                            stack.push(Join {
                                pc: rpc,
                                second: pc.wrapping_add(bi),
                                mask: taken,
                                parent: mask,
                                first: true,
                            });
                            mask &= !taken;
                        }
                    }
                    0x2b => {
                        let storing = word >> 31 != 0;
                        width = match f {
                            0 | 4 => 1,
                            1 | 5 => 2,
                            2 => 4,
                            _ => return Err("unsupported private width".into()),
                        };
                        if private_size == 0 {
                            return Err("private-memory allocation missing".into());
                        }
                        kind = if storing { STORE } else { LOAD };
                        sources.push(r1);
                        if storing {
                            sources.push(r2);
                        } else {
                            dest = Some(rd);
                        }
                        let offset = if storing {
                            sx((((word >> 25) & 63) << 5) | ((word >> 7) & 31), 11)
                        } else {
                            sx((word >> 20) & 2047, 11)
                        };
                        for i in 0..nt as usize {
                            if active(i) {
                                let a = required(v[r1][i], pc)?.wrapping_add(offset);
                                if a >= private_size {
                                    return Err(format!(
                                        "private address exceeds compiler allocation at {pc:08x}"
                                    ));
                                }
                                let physical = 0x60000000
                                    + block * wpb * nt * private_size
                                    + wpb * nt * (a & !3)
                                    + (warp * nt + i as u32) * 4
                                    + (a & 3);
                                addresses.push(physical as u64);
                                if storing {
                                    store(&mut mem, physical, width, v[r2][i]);
                                } else {
                                    v[rd][i] = load(&mem, physical, width, f < 4);
                                }
                            }
                        }
                    }
                    0x7b => {
                        let storing = [3, 6, 7].contains(&f);
                        width = match f {
                            0 | 4 | 7 => 1,
                            1 | 3 | 5 => 2,
                            2 | 6 => 4,
                            _ => return Err("unsupported vector width".into()),
                        };
                        kind = if storing { STORE } else { LOAD };
                        sources.push(r1);
                        if storing {
                            sources.push(r2);
                        } else {
                            dest = Some(rd);
                        }
                        for i in 0..nt as usize {
                            if active(i) {
                                let a = required(v[r1][i], pc)?.wrapping_add(if storing {
                                    simm
                                } else {
                                    imm
                                });
                                addresses.push(a as u64);
                                if storing {
                                    store(&mut mem, a, width, v[r2][i]);
                                } else {
                                    v[rd][i] = load(&mem, a, width, f < 4);
                                }
                            }
                        }
                    }
                    0x0a => {
                        let shape = (word >> 25) & 7;
                        let ab = word >> 28;
                        if word & (1 << 12) == 0 || ![(3, 1), (3, 2), (7, 0)].contains(&(shape, ab))
                        {
                            return Err(format!("unsupported MMA shape/type at {pc:08x}"));
                        }
                        kind = match ab {
                            2 => MMA_BF16,
                            1 => MMA_F16,
                            _ => MMA_TF32,
                        };
                        if rd + 8 > 256 || r1 + 4 > 256 || r2 + 4 > 256 {
                            return Err("MMA register group exceeds RF".into());
                        }
                        sources.extend(r1..r1 + 4);
                        sources.extend(r2..r2 + 4);
                        sources.extend(rd..rd + 8);
                        dest = Some(rd);
                        extra_dests.extend(rd + 1..rd + 8);
                        for reg in rd..rd + 8 {
                            for i in 0..nt as usize {
                                if active(i) {
                                    v[reg][i] = None;
                                }
                            }
                        }
                    }
                    0x42 => {
                        if f != 1 || !(8..=11).contains(&fun) {
                            return Err(format!("unsupported shuffle at {pc:08x}"));
                        }
                        kind = SHUFFLE;
                        sources.push(r2);
                        dest = Some(rd);
                        let amount = ((word >> 15) & 31) as usize;
                        let input = v[r2].clone();
                        for i in 0..nt as usize {
                            if active(i) {
                                let source = match fun {
                                    8 => i ^ amount,
                                    9 => amount,
                                    10 => i.checked_sub(amount).unwrap_or(i),
                                    11 => {
                                        if i + amount < nt as usize {
                                            i + amount
                                        } else {
                                            i
                                        }
                                    }
                                    _ => unreachable!(),
                                };
                                v[rd][i] = if source < nt as usize {
                                    input[source]
                                } else {
                                    None
                                };
                            }
                        }
                    }
                    0x5a => {
                        if f > 1 || fun > 2 {
                            return Err(format!("unsupported packed compute at {pc:08x}"));
                        }
                        kind = PACKED;
                        sources.extend([r1, r2]);
                        dest = Some(rd);
                        if fun == 2 {
                            sources.push(rd);
                        }
                        for i in 0..nt as usize {
                            if active(i) {
                                v[rd][i] = None;
                            }
                        }
                    }
                    0x7a => {
                        if f != 0 || fun > 3 {
                            return Err(format!("unsupported precision conversion at {pc:08x}"));
                        }
                        kind = CONVERT;
                        sources.push(r2);
                        dest = Some(rd);
                        for i in 0..nt as usize {
                            if active(i) {
                                v[rd][i] = v[r2][i].and_then(|a| match fun {
                                    2 => Some(a << 16),
                                    3 => Some(a >> 16),
                                    _ => None,
                                });
                            }
                        }
                    }
                    0x2a => {
                        if f > 2 || fun > 9 {
                            return Err(format!("unsupported SFU at {pc:08x}"));
                        }
                        kind = SFU;
                        sources.push(r2);
                        dest = Some(rd);
                        for i in 0..nt as usize {
                            if active(i) {
                                v[rd][i] = None;
                            }
                        }
                    }
                    0x57 if f == 7 => {
                        sources.push(256 + r1);
                        vl = required(x[r1], pc)?.min(nt);
                        x[rd] = Some(vl);
                        dest = Some(256 + rd);
                    }
                    0x57 => {
                        kind = VECTOR;
                        dest = Some(rd);
                        if fun == 0x14 && f == 2 && ((word >> 15) & 31) == 17 {
                            for i in 0..nt as usize {
                                if active(i) {
                                    v[rd][i] = Some(i as u32);
                                }
                            }
                        } else {
                            let scalar = f == 4 || f == 5 || f == 6;
                            let immediate = f == 3;
                            let unary = fun == 0x17 && word & (1 << 25) != 0;
                            let merging = fun == 0x17 && !unary;
                            if word & (1 << 25) == 0 {
                                sources.push(0);
                            }
                            if !unary {
                                sources.push(r2);
                            }
                            if !immediate {
                                sources.push(if scalar { 256 + r1 } else { r1 });
                            }
                            let fp = f == 1 || f == 5;
                            if !fp && (f == 2 || f == 6) && (0x29..=0x2f).contains(&fun) {
                                sources.push(rd);
                            }
                            if fp {
                                kind = match fun {
                                    0 | 2 => FADD,
                                    4 | 6 => FMAX,
                                    0x24 => FMUL,
                                    0x28 | 0x29 | 0x2a | 0x2b | 0x2c | 0x2d | 0x2e | 0x2f => FMA,
                                    0x12 => {
                                        if ((word >> 15) & 31) < 2 {
                                            FTOI
                                        } else {
                                            ITOF
                                        }
                                    }
                                    8 | 9 | 10 | 0x17 => VECTOR,
                                    0x18 | 0x19 | 0x1b | 0x1c | 0x1d | 0x1f => FCMP,
                                    _ => {
                                        return Err(format!(
                                            "missing FP instruction at {pc:08x}: {word:08x}"
                                        ))
                                    }
                                };
                                if kind == FMA && fun != 0x24 {
                                    sources.push(rd);
                                }
                            }
                            for i in 0..nt as usize {
                                if active(i) {
                                    if word & (1 << 25) == 0
                                        && !merging
                                        && required(v[0][i], pc)? == 0
                                    {
                                        continue;
                                    }
                                    let b = if immediate {
                                        Some(if exti {
                                            sx(
                                                (((word >> 15) & 31) | (((ext >> 6) & 63) << 5))
                                                    as u32,
                                                11,
                                            )
                                        } else {
                                            sx((word >> 15) & 31, 5)
                                        })
                                    } else if scalar {
                                        x[r1]
                                    } else {
                                        v[r1][i]
                                    };
                                    let a = v[r2][i];
                                    v[rd][i] = if unary {
                                        b
                                    } else if merging {
                                        v[0][i].and_then(|m| if m != 0 { b } else { a })
                                    } else if fp {
                                        match (a, b) {
                                            (Some(a), Some(b)) => {
                                                let (a, b) = (f32::from_bits(a), f32::from_bits(b));
                                                Some(match fun {
                                                    0 => (a + b).to_bits(),
                                                    2 => (a - b).to_bits(),
                                                    4 => a.min(b).to_bits(),
                                                    6 => a.max(b).to_bits(),
                                                    0x24 => (a * b).to_bits(),
                                                    0x18 => u32::from(a == b),
                                                    0x19 => u32::from(a <= b),
                                                    0x1b => u32::from(a < b),
                                                    0x1c => u32::from(a != b),
                                                    0x1d => u32::from(a > b),
                                                    0x1f => u32::from(a >= b),
                                                    _ => {
                                                        v[rd][i] = None;
                                                        continue;
                                                    }
                                                })
                                            }
                                            _ => None,
                                        }
                                    } else {
                                        match fun{
                                0=>binary(a,b,u32::wrapping_add),2=>binary(a,b,u32::wrapping_sub),3=>binary(b,a,u32::wrapping_sub),
                                9=>binary(a,b,|a,b|a&b),10=>binary(a,b,|a,b|a|b),11=>if r1==r2{Some(0)}else{binary(a,b,|a,b|a^b)},
                                0x25 if f!=2&&f!=6=>binary(a,b,|a,b|a.wrapping_shl(b&31)),0x28=>binary(a,b,|a,b|a.wrapping_shr(b&31)),0x29 if f!=2&&f!=6=>binary(a,b,|a,b|((a as i32)>>(b&31)) as u32),

                                0x18 if f==2=>binary(a,b,|a,b|a & !b),
                                0x19 if f==2=>binary(a,b,|a,b|a & b),
                                0x1a if f==2=>binary(a,b,|a,b|a | b),
                                0x1b if f==2=>binary(a,b,|a,b|a ^ b),
                                0x18=>binary(a,b,|a,b|u32::from(a==b)),
                                0x19=>binary(a,b,|a,b|u32::from(a!=b)),
                                0x1a=>binary(a,b,|a,b|u32::from(a<b)),
                                0x1b=>binary(a,b,|a,b|u32::from((a as i32)<(b as i32))),
                                0x1c=>binary(a,b,|a,b|u32::from(a<=b)),
                                0x1d=>binary(a,b,|a,b|u32::from((a as i32)<=(b as i32))),
                                0x1e=>binary(a,b,|a,b|u32::from(a>b)),
                                0x1f=>binary(a,b,|a,b|u32::from((a as i32)>(b as i32))),
                                0x20 if f==2||f==6=>binary(a,b,|a,b|if b==0{u32::MAX}else{a/b}),
                                0x21 if f==2||f==6=>binary(a,b,|a,b|if b==0{u32::MAX}else{(a as i32).wrapping_div(b as i32) as u32}),
                                0x22 if f==2||f==6=>binary(a,b,|a,b|if b==0{a}else{a%b}),
                                0x23 if f==2||f==6=>binary(a,b,|a,b|if b==0{a}else{(a as i32).wrapping_rem(b as i32) as u32}),
                                0x24 if f==2||f==6=>binary(a,b,|a,b|(((a as u64)*(b as u64))>>32)as u32),
                                0x25 if f==2||f==6=>binary(a,b,u32::wrapping_mul),
                                0x26 if f==2||f==6=>binary(a,b,|a,b|(((a as i32 as i64)*(b as i64))>>32)as u32),
                                0x27 if f==2||f==6=>binary(a,b,|a,b|(((a as i32 as i64)*(b as i32 as i64))>>32)as u32),
                                0x29 if f==2||f==6=>binary(v[rd][i],b,u32::wrapping_mul).and_then(|c|binary(Some(c),a,u32::wrapping_add)),
                                0x2b if f==2||f==6=>binary(v[rd][i],b,u32::wrapping_mul).and_then(|c|binary(a,Some(c),u32::wrapping_sub)),
                                0x2d if f==2||f==6=>binary(a,b,u32::wrapping_mul).and_then(|c|binary(v[rd][i],Some(c),u32::wrapping_add)),
                                0x2f if f==2||f==6=>binary(a,b,u32::wrapping_mul).and_then(|c|binary(v[rd][i],Some(c),u32::wrapping_sub)),
                                _=>return Err(format!("missing vector instruction at {pc:08x}: {word:08x}"))
                            }
                                    };
                                }
                            }
                        }
                    }
                    _ => return Err(format!("missing opcode at pc={pc:08x} word={word:08x}")),
                }
                if opcode != 0x0b || !(f == 2 || f == 3) {
                    ext = 0;
                    exti = false;
                }
                x[0] = Some(0);
                if (kind == LOAD || kind == STORE) && addresses.is_empty() {
                    pc = next;
                    continue;
                }
                if addresses.iter().any(|a| *a % width as u64 != 0) {
                    return Err(format!("misaligned memory instruction at {pc:08x}"));
                }
                ops.push(Op {
                    kind,
                    block: block as usize,
                    warp: warp as usize,
                    sources,
                    dest,
                    addresses,
                    deps: Vec::new(),
                    extra_dests,
                    width,
                    active_mask,
                });
                pc = next;
            }
        }
    }
    if ops.is_empty() {
        return Err("empty dynamic program".into());
    }
    Ok(ops)
}

pub(super) fn compact(ops: &[Op], launch: &[u64]) -> Vec<u64> {
    let extended = ops.iter().any(|o| {
        o.kind > 10
            || o.width != 4
            || !o.extra_dests.is_empty()
            || o.active_mask != (1u64 << launch[5]) - 1
    });
    let mut data = vec![
        if extended { 0x56545339 } else { 0x56545337 },
        ops.len() as u64,
        launch[4],
        launch[6],
        launch[7],
        launch[8],
    ];
    for o in ops {
        data.extend([
            o.kind as u64,
            o.block as u64,
            o.warp as u64,
            if extended {
                (usize::from(o.dest.is_some()) + o.extra_dests.len()) as u64
            } else {
                o.dest.map(|d| d as u64).unwrap_or(u64::MAX)
            },
            o.sources.len() as u64,
            o.addresses.len() as u64,
            0,
        ]);
        if extended {
            data.push(o.width as u64);
            data.push(o.active_mask);
            data.extend(o.dest.iter().chain(o.extra_dests.iter()).map(|v| *v as u64));
        }
        data.extend(o.sources.iter().map(|v| *v as u64));
        data.extend(&o.addresses);
    }
    data
}
