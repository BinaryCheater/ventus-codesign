//! Compact port of source-events-v7. No graph, names, closures or tensor values.
mod provider;
use std::cmp::{max, Reverse};
use std::collections::{BinaryHeap, HashMap, HashSet, VecDeque};
use std::ffi::c_void;
use std::hash::{BuildHasherDefault, Hasher};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::slice;
#[derive(Default)]
struct NumericHasher(u64);
impl Hasher for NumericHasher {
    fn finish(&self) -> u64 {
        self.0
    }
    fn write(&mut self, bytes: &[u8]) {
        for b in bytes {
            self.write_u64(*b as u64);
        }
    }
    fn write_u64(&mut self, v: u64) {
        self.0 = (self.0.rotate_left(5) ^ v).wrapping_mul(0x517cc1b727220a95);
    }
    fn write_usize(&mut self, v: usize) {
        self.write_u64(v as u64);
    }
    fn write_u8(&mut self, v: u8) {
        self.write_u64(v as u64);
    }
}
type NumericMap<K, V> = HashMap<K, V, BuildHasherDefault<NumericHasher>>;
type Time = u64;
const NONE: usize = usize::MAX;
const SCALAR: usize = 0;
const VECTOR: usize = 1;
const FADD: usize = 2;
const FMAX: usize = 3;
const FMA: usize = 4;
const FTOI: usize = 5;
const ITOF: usize = 6;
const TENSOR: usize = 7;
const LOAD: usize = 8;
const STORE: usize = 9;
const BARRIER: usize = 10;
const FPADD: usize = 11;
const PACKED: usize = 12;
const CONVERT: usize = 13;
const SFU: usize = 14;
const MMA_BF16: usize = 15;
const MMA_F16: usize = 16;
const MMA_TF32: usize = 17;
const FMUL: usize = 18;
const FCMP: usize = 19;
const SHUFFLE: usize = 20;
const KIND_NAMES: [&str; 21] = [
    "scalar", "vector", "fadd", "fmax", "fma", "ftoi", "itof", "tensor", "load", "store",
    "barrier", "fp_add", "packed", "convert", "sfu", "mma_bf16", "mma_f16", "mma_tf32", "fmul",
    "fcmp", "shuffle",
];
const RESULT_LEN: usize = 39;
// Hardware order is the existing Python dataclass order.
const SMS: usize = 0;
const WARPS: usize = 1;
const BLOCKS: usize = 2;
const RFB: usize = 4;
const RFR: usize = 5;
const RFW: usize = 6;
const WB: usize = 7;
const COL: usize = 8;
const VGPR: usize = 9;
const SGPR: usize = 10;
const TN: usize = 12;
const TU: usize = 14;
const LDS: usize = 15;
const LDB: usize = 16;
const LDP: usize = 17;
const LINE: usize = 18;
const L1S: usize = 19;
const L1W: usize = 20;
const L1M: usize = 21;
const L1SUB: usize = 22;
const L1WRITE: usize = 23;
const L2S: usize = 24;
const L2W: usize = 25;
const L2M: usize = 26;
const LSU: usize = 27;
const LSUW: usize = 28;
const CHANNELS: usize = 29;
const BW: usize = 30;
const MLAT: usize = 31;
// Results: cycles, instructions, requested bytes, simulated edges, idle skipped,
// followed by kind counts (0..10) and the 13 existing memory/stall counters.
const MEMORY_READ: usize = 26;
const MEMORY_WRITE: usize = 27;
const L2_HIT: usize = 28;
const L2_MISS: usize = 29;
const L1_MERGE: usize = 30;
const L1_HIT: usize = 31;
const L1_WRITE_MISS: usize = 32;
const L1_READ_MISS: usize = 33;
const LDS_ROUNDS: usize = 34;
const WB_STALL: usize = 35;
const EXEC_STALL: usize = 36;
const FPU_BACK: usize = 37;
const FPU_ARB: usize = 38;
#[derive(Clone, Copy, Debug)]
struct Tag {
    line: u64,
    fill: Time,
    dirty: bool,
    way: usize,
}
#[derive(Default)]
struct Cache {
    l1: HashMap<(usize, usize), VecDeque<Tag>>,
    l2: HashMap<usize, VecDeque<Tag>>,
    lfsr: u16,
}
#[derive(Clone, Copy, Debug)]
struct Booking {
    start: Time,
    end: Time,
}
#[derive(Default)]
struct Resource {
    slots: Vec<Vec<Booking>>,
    history: VecDeque<Time>,
}
#[derive(Clone, Copy, Hash, PartialEq, Eq)]
struct Key(u8, usize, usize, u64);
struct Builder<'a> {
    hw: &'a [usize; 32],
    cache: &'a mut Cache,
    resources: NumericMap<Key, Resource>,
    groups: Vec<u64>,
    bank_counts: Vec<usize>,
    calendars: Vec<Key>,
    writes: Time,
    stats: [u64; RESULT_LEN],
    shared: Vec<usize>,
    intervals: &'a [u64],
    retain: usize,
    target: &'a [u64; 10],
}
impl<'a> Builder<'a> {
    fn new(
        hw: &'a [usize; 32],
        cache: &'a mut Cache,
        intervals: &'a [u64],
        target: &'a [u64; 10],
    ) -> Self {
        for tags in cache.l1.values_mut().chain(cache.l2.values_mut()) {
            for x in tags {
                x.fill = 0;
                x.dirty = false;
            }
        }
        Self {
            hw,
            target,
            cache,
            resources: NumericMap::default(),
            groups: Vec::with_capacity(hw[3]),
            bank_counts: vec![0; hw[LDB]],
            calendars: Vec::new(),
            writes: 0,
            stats: [0; RESULT_LEN],
            shared: vec![0; hw[SMS]],
            intervals,
            retain: [L2M, L1M, L1SUB, L1WRITE, LSU, LSUW]
                .into_iter()
                .map(|i| hw[i])
                .max()
                .unwrap(),
        }
    }
    fn record(&mut self, key: Key, t: Time) {
        let history = &mut self.resources.entry(key).or_default().history;
        history.push_back(t);
        if history.len() > self.retain {
            history.pop_front();
        }
    }
    fn capacity(&self, key: Key, r: Time, n: usize) -> Time {
        if let Some(res) = self.resources.get(&key) {
            if res.history.len() >= n {
                return max(r, res.history[res.history.len() - n]);
            }
        }
        r
    }
    fn last(&self, key: Key) -> Time {
        self.resources
            .get(&key)
            .and_then(|r| r.history.back().copied())
            .unwrap_or(0)
    }
    fn reserve(&mut self, key: Key, ready: Time, interval: Time, capacity: usize) -> Time {
        let res = self.resources.entry(key).or_default();
        if res.slots.is_empty() {
            self.calendars.push(key);
            res.slots.resize(capacity, Vec::new());
        }
        assert_eq!(res.slots.len(), capacity);
        let mut best = (u64::MAX, 0);
        for (i, slot) in res.slots.iter().enumerate() {
            let mut start = ready;
            // Slots are ordered and non-overlapping; expired prefixes need
            // no linear scan, including when future reservations are inserted.
            let first = slot.partition_point(|b| b.end <= start);
            for b in &slot[first..] {
                if start + interval <= b.start {
                    break;
                }
                start = b.end;
            }
            best = best.min((start, i));
        }
        let b = Booking {
            start: best.0,
            end: best.0 + interval,
        };
        let slot = &mut res.slots[best.1];
        let pos = slot.partition_point(|x| x.start <= b.start);
        slot.insert(pos, b);
        self.record(key, best.0);
        best.0
    }
    fn prune(&mut self, clock: Time) {
        for key in &self.calendars {
            let r = self.resources.get_mut(key).unwrap();
            for s in &mut r.slots {
                s.retain(|b| b.end > clock);
            }
        }
    }
    fn transfer(&mut self, r: Time, line: u64, write: bool) -> Time {
        let h = self.hw;
        let interval = h[LINE].div_ceil(h[BW]) as u64;
        let ch = (line / h[LINE] as u64) as usize % h[CHANNELS];
        let start = self.reserve(Key(0, ch, 0, 0), r + 2, interval, 1);
        let end = start + h[MLAT] as u64 + interval + 2;
        self.stats[if write { MEMORY_WRITE } else { MEMORY_READ }] += h[LINE] as u64;
        if write {
            self.writes = max(self.writes, end);
        }
        end
    }
    fn lower(&mut self, r: Time, line: u64, allocate: bool) -> Time {
        let h = self.hw;
        let set = (line / h[LINE] as u64) as usize % h[L2S];
        let mut probe = self.reserve(Key(1, 0, 0, 0), r + 1, 1, 1);
        let victim = (self.cache.lfsr as usize) & (h[L2W] - 1);
        let x = self.cache.lfsr;
        let feedback = (x ^ (x >> 1) ^ (x >> 3) ^ (x >> 4)) & 1;
        self.cache.lfsr = if x == 0 { 1 } else { (x << 1) | feedback };
        let cache = self.cache.l2.entry(set).or_default();
        if let Some(pos) = cache.iter().position(|x| x.line == line) {
            let tag = cache.remove(pos).unwrap();
            cache.push_back(tag);
            self.stats[L2_HIT] += 1;
            return max(probe + 2, tag.fill + 1);
        }
        self.stats[L2_MISS] += 1;
        if allocate {
            if let Some(pos) = cache.iter().position(|x| x.way == victim) {
                probe = max(probe, cache.remove(pos).unwrap().fill);
            }
        }
        let accepted = self.capacity(Key(2, 0, 0, 0), probe + 1, h[L2M]);
        let done = self.transfer(accepted, line, false) + 3;
        self.record(Key(2, 0, 0, 0), done);
        if allocate {
            self.cache.l2.get_mut(&set).unwrap().push_back(Tag {
                line,
                fill: done,
                dirty: false,
                way: victim,
            });
        }
        done
    }
    fn global(&mut self, r: Time, sm: usize, line: u64, write: bool) -> Time {
        let h = self.hw;
        let set = (line / h[LINE] as u64) as usize % h[L1S];
        let mut probe = self.reserve(Key(3, sm, 0, 0), r, 1, 1);
        let cache = self.cache.l1.entry((sm, set)).or_default();
        if let Some(pos) = cache.iter().position(|x| x.line == line) {
            let mut tag = cache.remove(pos).unwrap();
            let fill = tag.fill;
            tag.dirty |= write;
            cache.push_back(tag);
            if probe < fill {
                self.stats[L1_MERGE] += 1;
                probe = self.capacity(Key(4, sm, 0, line), probe, h[L1SUB]);
            } else {
                self.stats[L1_HIT] += 1;
            }
            let done = max(probe + 3, fill + 1);
            self.record(Key(4, sm, 0, line), done);
            return done;
        }
        self.stats[if write { L1_WRITE_MISS } else { L1_READ_MISS }] += 1;
        if write {
            let start = self.capacity(Key(5, sm, 0, 0), probe + 2, h[L1WRITE]);
            let lower = self.lower(start + 2, line, false);
            let done = self.transfer(lower, line, true);
            self.record(Key(5, sm, 0, 0), done);
            return start + 1;
        }
        if cache.len() >= h[L1W] {
            let old = cache.pop_front().unwrap();
            // A removed tag cannot merge another request into its fill.
            // No calendar uses these per-line subscriber histories.
            self.resources.remove(&Key(4, sm, 0, old.line));
            probe = max(probe, old.fill);
            if old.dirty {
                probe = self.transfer(probe, old.line, true);
            }
        }
        let start = self.capacity(Key(6, sm, 0, 0), probe + 2, h[L1M]);
        let done = self.lower(start + 2, line, true) + 4;
        self.cache.l1.get_mut(&(sm, set)).unwrap().push_back(Tag {
            line,
            fill: done,
            dirty: false,
            way: 0,
        });
        self.record(Key(6, sm, 0, 0), done);
        let history = &mut self
            .resources
            .entry(Key(4, sm, 0, line))
            .or_default()
            .history;
        history.clear();
        history.push_back(done);
        done
    }
    fn memory(&mut self, issue: Time, op: &Op, sm: usize, wid: usize) -> Time {
        let h = self.hw;
        let mut groups = std::mem::take(&mut self.groups);
        groups.clear();
        for &a in &op.addresses {
            let line = a / h[LINE] as u64 * h[LINE] as u64;
            if !groups.contains(&line) {
                groups.push(line);
            }
        }
        let mut gate = self.capacity(Key(7, sm, 0, 0), issue, h[LSU]);
        gate = self.capacity(Key(8, sm, wid, 0), gate, h[LSUW]);
        gate = max(gate, self.last(Key(9, sm, 0, 0)));
        if op
            .addresses
            .iter()
            .all(|a| *a >= 0x70000000 && *a < 0x70000000 + h[LDS] as u64)
        {
            let interval = self.intervals[self.shared[sm] % self.intervals.len()];
            self.shared[sm] += 1;
            gate = self.reserve(Key(10, sm, 0, 0), gate, interval, 1);
        }
        let first = self.reserve(Key(11, sm, 0, 0), gate, 2 + groups.len() as u64, 1);
        let mut ends = 0;
        let mut grants = 0;
        for (i, line) in groups.iter().enumerate() {
            let r = first + 3 + i as u64;
            if *line >= 0x70000000 && *line < 0x70000000 + h[LDS] as u64 {
                self.bank_counts.fill(0);
                for a in &op.addresses {
                    if a / h[LINE] as u64 * h[LINE] as u64 == *line {
                        self.bank_counts[(a / 4) as usize % h[LDB]] += 1;
                    }
                }
                let rounds = self.bank_counts.iter().max().unwrap().div_ceil(h[LDP]) as u64;
                self.stats[LDS_ROUNDS] += rounds;
                let start = self.reserve(
                    Key(12, sm, 0, 0),
                    r,
                    rounds + u64::from(op.kind == STORE),
                    1,
                );
                let last = start + rounds - 1;
                ends = max(ends, last + 3);
                grants = max(grants, last);
            } else {
                ends = max(ends, self.global(r, sm, *line, op.kind == STORE));
                grants = max(grants, r);
            }
        }
        self.record(Key(9, sm, 0, 0), grants + 1);
        let done = self.reserve(Key(13, sm, 0, 0), ends + 1, 1, 1);
        self.record(Key(7, sm, 0, 0), done);
        self.record(Key(8, sm, wid, 0), done);
        self.groups = groups;
        done
    }
}
#[derive(Clone, Debug)]
struct Op {
    kind: usize,
    block: usize,
    warp: usize,
    sources: Vec<usize>,
    dest: Option<usize>,
    addresses: Vec<u64>,
    deps: Vec<usize>,
    extra_dests: Vec<usize>,
    width: usize,
    active_mask: u64,
}
#[derive(Clone, Copy, Debug)]
struct Token {
    op: usize,
    sm: usize,
    wid: usize,
    time: Time,
}
#[derive(Clone)]
struct Pipe {
    sm: usize,
    kind: usize,
    unit: usize,
    stages: VecDeque<Option<Token>>,
    occupied: usize,
    arbitration_key: String,
    next_accept: Time,
    interval: Time,
}
impl Pipe {
    fn input_ready(&self, output: bool) -> bool {
        output || self.occupied < self.stages.len()
    }
    fn output(&self) -> Option<Token> {
        *self.stages.back().unwrap()
    }
}
struct Stream {
    block: usize,
    warp: usize,
    ops: Vec<usize>,
    pc: usize,
    busy: bool,
    regs: Vec<usize>,
    last_issue: Option<Time>,
    collect_after: Time,
}
struct Block {
    sm: Option<usize>,
    wids: Vec<usize>,
    gate: Time,
    ops: usize,
    retired: usize,
    end: Time,
    streams: Vec<usize>,
    live: Vec<usize>,
}
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
struct Pending {
    time: Time,
    serial: u64,
    action: u8,
    op: usize,
    sm: usize,
    wid: usize,
    collector: usize,
}
struct Engine<'a> {
    b: Builder<'a>,
    ops: Vec<Op>,
    streams: Vec<Stream>,
    op_stream: Vec<usize>,
    resident_streams: Vec<Vec<usize>>,
    blocks: Vec<Block>,
    waiting: VecDeque<usize>,
    resident: usize,
    wpb: usize,
    sm_blocks: Vec<usize>,
    warp_free: Vec<Vec<bool>>,
    sm_release: Vec<Time>,
    last_alloc: usize,
    collectors: Vec<Vec<Option<Token>>>,
    issue_ready: Vec<[Vec<(usize, Token)>; 2]>,
    rr_collect: Vec<[usize; 2]>,
    rr_issue: Vec<[usize; 2]>,
    completion: Vec<Option<Time>>,
    pending: BinaryHeap<Reverse<Pending>>,
    serial: u64,
    pipes: Vec<Pipe>,
    pipe_ids: Vec<Vec<Vec<usize>>>,
    sm_pipes: Vec<Vec<usize>>,
    lsu_buffer: Vec<Option<Token>>,
    lsu_output: Vec<VecDeque<Token>>,
    address_until: Vec<Time>,
    lsu_count: Vec<usize>,
    lsu_warp: Vec<Vec<usize>>,
    clock: Time,
    end: Time,
    recipe: Option<(Vec<u32>, Vec<u64>)>,
    free_ops: Vec<usize>,
    index_buffers: Vec<Vec<usize>>,
    register_buffers: Vec<Vec<usize>>,
    written: HashSet<u64>,
    wb_progress: Vec<usize>,
    consumed_scratch: Vec<bool>,
    transfer_scratch: Vec<Option<Token>>,
    issue_scratch: Vec<Option<Token>>,
    wb_scratch: Vec<(usize, usize, Option<usize>, Token)>,
    wb_banks: Vec<[usize; 2]>,
    tensor_next: Vec<Vec<Time>>,
}
impl<'a> Engine<'a> {
    fn new(
        mut b: Builder<'a>,
        mut ops: Vec<Op>,
        wpb: usize,
        vgpr: usize,
        sgpr: usize,
        lds: usize,
    ) -> Self {
        let h = b.hw;
        let mut resident = h[BLOCKS].min(h[WARPS] / wpb);
        for (cap, use_) in [(h[VGPR], vgpr * wpb), (h[SGPR], sgpr * wpb), (h[LDS], lds)] {
            if use_ > 0 {
                resident = resident.min(cap / use_);
            }
        }
        assert!(resident > 0);
        let mut streams: Vec<Stream> = Vec::new();
        let mut op_stream = vec![0; ops.len()];
        let mut blocks: Vec<Block> = Vec::new();
        let mut block_map = HashMap::new();
        let mut preceding: Vec<Vec<usize>> = Vec::new();
        let mut last_fence: Vec<Option<usize>> = Vec::new();
        for i in 0..ops.len() {
            let original = ops[i].block;
            let block = if let Some(b) = block_map.get(&original) {
                *b
            } else {
                let b = blocks.len();
                blocks.push(Block {
                    sm: None,
                    wids: Vec::new(),
                    gate: 0,
                    ops: 0,
                    retired: 0,
                    end: 0,
                    streams: Vec::new(),
                    live: Vec::new(),
                });
                block_map.insert(original, b);
                preceding.push(Vec::new());
                last_fence.push(None);
                b
            };
            ops[i].block = block;
            blocks[block].ops += 1;
            blocks[block].live.push(i);
            if ops[i].kind == BARRIER {
                ops[i].deps.extend_from_slice(&preceding[block]);
                last_fence[block] = Some(i);
            } else if let Some(f) = last_fence[block] {
                ops[i].deps.push(f);
            }
            preceding[block].push(i);
            let warp = ops[i].warp;
            let st = if let Some(j) = streams
                .iter()
                .position(|s| s.block == block && s.warp == warp)
            {
                j
            } else {
                let j = streams.len();
                blocks[block].streams.push(j);
                streams.push(Stream {
                    block,
                    warp,
                    ops: Vec::new(),
                    pc: 0,
                    busy: false,
                    regs: vec![NONE; 512],
                    last_issue: None,
                    collect_after: 0,
                });
                j
            };
            streams[st].ops.push(i);
            op_stream[i] = st;
        }
        b.stats[1] = ops.len() as u64;
        b.stats[2] = ops
            .iter()
            .filter(|o| o.kind == LOAD || o.kind == STORE)
            .map(|o| o.width as u64 * o.addresses.len() as u64)
            .sum();
        let count = ops.len();
        let nb = blocks.len();
        Self {
            b,
            ops,
            streams,
            op_stream,
            resident_streams: vec![Vec::new(); h[SMS]],
            blocks,
            waiting: (0..nb).collect(),
            resident,
            wpb,
            sm_blocks: vec![0; h[SMS]],
            warp_free: vec![vec![true; h[WARPS]]; h[SMS]],
            sm_release: vec![0; h[SMS]],
            last_alloc: h[SMS] - 1,
            collectors: vec![vec![None; h[COL]]; h[SMS]],
            issue_ready: (0..h[SMS]).map(|_| [Vec::new(), Vec::new()]).collect(),
            rr_collect: vec![[0; 2]; h[SMS]],
            rr_issue: vec![[0; 2]; h[SMS]],
            completion: vec![None; count],
            pending: BinaryHeap::new(),
            serial: 0,
            pipes: Vec::new(),
            pipe_ids: vec![vec![Vec::new(); KIND_NAMES.len()]; h[SMS]],
            sm_pipes: vec![Vec::new(); h[SMS]],
            lsu_buffer: vec![None; h[SMS]],
            lsu_output: vec![VecDeque::new(); h[SMS]],
            address_until: vec![0; h[SMS]],
            lsu_count: vec![0; h[SMS]],
            lsu_warp: vec![vec![0; h[WARPS]]; h[SMS]],
            clock: 0,
            end: 0,
            recipe: None,
            free_ops: Vec::new(),
            index_buffers: Vec::new(),
            register_buffers: Vec::new(),
            written: HashSet::new(),
            wb_progress: vec![0; count],
            consumed_scratch: Vec::new(),
            transfer_scratch: Vec::new(),
            issue_scratch: Vec::new(),
            wb_scratch: Vec::new(),
            wb_banks: vec![[0, 0]; h[RFB]],
            tensor_next: vec![vec![0; h[TU]]; h[SMS]],
        }
    }
    fn streaming(b: Builder<'a>, words: Vec<u32>, launch: Vec<u64>) -> Self {
        assert_eq!(
            launch[4], 1,
            "streaming provider currently supports one warp per block"
        );
        assert_eq!(
            launch[5] as usize, b.hw[3],
            "program lane width differs from hardware"
        );
        let count = launch[3] as usize;
        let mut engine = Self::new(
            b,
            Vec::new(),
            launch[4] as usize,
            launch[6] as usize,
            launch[7] as usize,
            launch[8] as usize,
        );
        for block in 0..count {
            engine.blocks.push(Block {
                sm: None,
                wids: Vec::new(),
                gate: 0,
                ops: 0,
                retired: 0,
                end: 0,
                streams: vec![block],
                live: Vec::new(),
            });
            engine.streams.push(Stream {
                block,
                warp: 0,
                ops: Vec::new(),
                pc: 0,
                busy: false,
                regs: Vec::new(),
                last_issue: None,
                collect_after: 0,
            });
        }
        engine.waiting = (0..count).collect();
        engine.recipe = Some((words, launch));
        engine
    }
    fn materialize(&mut self, block: usize) {
        let Some((words, launch)) = &self.recipe else {
            return;
        };
        let mut parameters = launch.clone();
        parameters[3] = 1;
        parameters[16] = block as u64;
        let ops = provider::generate(words, &parameters).unwrap_or_else(|e| panic!("{e}"));
        let st = self.blocks[block].streams[0];
        let mut registers = self.register_buffers.pop().unwrap_or_default();
        registers.resize(512, NONE);
        registers.fill(NONE);
        self.streams[st].regs = registers;
        self.streams[st].ops = self.index_buffers.pop().unwrap_or_default();
        self.blocks[block].live = self.index_buffers.pop().unwrap_or_default();
        for mut op in ops {
            op.block = block;
            let id = if let Some(id) = self.free_ops.pop() {
                self.ops[id] = op;
                self.completion[id] = None;
                self.wb_progress[id] = 0;
                self.op_stream[id] = st;
                id
            } else {
                let id = self.ops.len();
                self.ops.push(op);
                self.completion.push(None);
                self.wb_progress.push(0);
                self.op_stream.push(st);
                id
            };
            self.b.stats[1] += 1;
            if self.ops[id].kind == LOAD || self.ops[id].kind == STORE {
                self.b.stats[2] += self.ops[id].width as u64 * self.ops[id].addresses.len() as u64;
            }
            self.blocks[block].live.push(id);
            self.streams[st].ops.push(id);
        }
        self.blocks[block].ops = self.blocks[block].live.len();
    }
    fn path(&self, op: usize) -> usize {
        usize::from(self.ops[op].kind == SCALAR || self.ops[op].kind == BARRIER)
    } // vector=0 scalar=1
    fn fpu(kind: usize) -> bool {
        [
            FADD, FMA, FMAX, FTOI, ITOF, FMUL, FCMP, CONVERT, PACKED, SFU,
        ]
        .contains(&kind)
    }
    fn pipe(&mut self, sm: usize, kind: usize, unit: usize) -> usize {
        if let Some(&i) = self.pipe_ids[sm][kind].get(unit) {
            return i;
        }
        assert_eq!(self.pipe_ids[sm][kind].len(), unit);
        if kind >= PACKED {
            assert!(
                self.b.target[0] == 1,
                "extended instructions require an explicit target"
            );
        }
        let latency = match kind {
            SCALAR | VECTOR | FADD => 1,
            FPADD | FTOI | ITOF | FMAX => 2,
            FMA => 3,
            TENSOR => 2 + 2 * (self.b.hw[TN].ilog2() as usize) + 2 + 2,
            PACKED => self.b.target[1] as usize,
            CONVERT => self.b.target[2] as usize,
            SFU => self.b.target[3] as usize,
            MMA_BF16 | MMA_F16 | MMA_TF32 => {
                let multiplies: usize = if kind == MMA_TF32 { 2048 } else { 4096 };
                let parallel =
                    self.b.hw[11] * self.b.hw[12] * self.b.hw[13] * self.b.target[6] as usize;
                self.b.target[4] as usize + multiplies.div_ceil(parallel) - 1
            }
            FMUL => self.b.target[7] as usize,
            FCMP => self.b.target[8] as usize,
            SHUFFLE => self.b.target[9] as usize,
            _ => panic!("unsupported pipeline"),
        };
        let interval = if (MMA_BF16..=MMA_TF32).contains(&kind) {
            let multiplies: usize = if kind == MMA_TF32 { 2048 } else { 4096 };
            let parallel =
                self.b.hw[11] * self.b.hw[12] * self.b.hw[13] * self.b.target[6] as usize;
            multiplies.div_ceil(parallel) as Time
        } else {
            1
        };
        let i = self.pipes.len();
        self.pipe_ids[sm][kind].push(i);
        self.sm_pipes[sm].push(i);
        self.pipes.push(Pipe {
            sm,
            kind,
            unit,
            stages: vec![None; latency].into(),
            occupied: 0,
            next_accept: 0,
            interval,
            arbitration_key: format!("({}, '{}', {})", sm, KIND_NAMES[kind], unit),
        });
        i
    }
    fn schedule(&mut self, token: Token, action: u8, collector: usize) {
        self.serial += 1;
        self.pending.push(Reverse(Pending {
            time: token.time,
            serial: self.serial,
            action,
            op: token.op,
            sm: token.sm,
            wid: token.wid,
            collector,
        }));
    }
    fn allocate(&mut self) {
        let h = self.b.hw;
        while let Some(&block) = self.waiting.front() {
            let choice = (0..h[SMS])
                .map(|offset| (self.last_alloc + 1 + offset) % h[SMS])
                .find(|s| {
                    self.sm_blocks[*s] < self.resident
                        && self.warp_free[*s].iter().filter(|x| **x).count() >= self.wpb
                });
            let Some(sm) = choice else { break };
            self.waiting.pop_front();
            self.materialize(block);
            let wids: Vec<_> = self.warp_free[sm]
                .iter()
                .enumerate()
                .filter(|(_, x)| **x)
                .take(self.wpb)
                .map(|(i, _)| i)
                .collect();
            for &w in &wids {
                self.warp_free[sm][w] = false;
            }
            if let Some((_, launch)) = &self.recipe {
                let delta = wids[0] as u64 * launch[8];
                for &id in &self.blocks[block].live {
                    for address in &mut self.ops[id].addresses {
                        if *address >= 0x70000000 && *address < 0x70000000 + launch[8] {
                            *address += delta;
                            assert!(*address < 0x70000000 + h[LDS] as u64);
                        }
                    }
                }
            }
            self.resident_streams[sm].extend(&self.blocks[block].streams);
            self.blocks[block].sm = Some(sm);
            self.blocks[block].wids = wids;
            self.blocks[block].gate = max(self.sm_release[sm], self.clock);
            self.sm_blocks[sm] += 1;
            self.last_alloc = sm;
        }
    }
    fn ready(&mut self, st: usize) -> Option<Time> {
        let s = &self.streams[st];
        if s.busy || s.pc == s.ops.len() || s.collect_after > self.clock {
            return None;
        }
        let o = &self.ops[s.ops[s.pc]];
        let b = &self.blocks[s.block];
        b.sm?;
        let mut r = b.gate;
        for &dep in &o.deps {
            r = max(r, self.completion[dep]? + 1);
        }
        for &reg in o
            .sources
            .iter()
            .chain(o.dest.iter())
            .chain(o.extra_dests.iter())
        {
            if reg == 256 {
                continue;
            }
            let writer = s.regs[reg];
            if writer != NONE {
                r = max(r, self.completion[writer]? + 1);
            }
        }
        if let Some(i) = s.last_issue {
            r = max(r, i + 1);
        }
        if r > self.clock {
            self.streams[st].collect_after = r;
            return None;
        }
        Some(r)
    }
    fn collect(&mut self) {
        let h = self.b.hw;
        for sm in 0..h[SMS] {
            if self.sm_blocks[sm] == 0 {
                continue;
            }
            let mut free_initial = self.collectors[sm]
                .iter()
                .enumerate()
                .filter(|(_, v)| v.is_none())
                .map(|(i, _)| i);
            let Some(first) = free_initial.next() else {
                continue;
            };
            let second = free_initial.next();
            for path in 0..2 {
                let Some(free) = self.collectors[sm].iter().position(|v| v.is_none()) else {
                    continue;
                };
                let demux = h[COL] == h[WARPS] && h[WARPS] > 1;
                if path == 1 && demux && second.is_none() {
                    continue;
                }
                let mut candidate: Option<(usize, usize, Time, usize)> = None;
                for idx in 0..self.resident_streams[sm].len() {
                    let st = self.resident_streams[sm][idx];
                    let s = &self.streams[st];
                    if s.busy
                        || s.collect_after > self.clock
                        || s.pc == s.ops.len()
                        || self.blocks[s.block].sm != Some(sm)
                        || self.path(s.ops[s.pc]) != path
                    {
                        continue;
                    }
                    if let Some(ready) = self.ready(st) {
                        let s = &self.streams[st];
                        let wid = self.blocks[s.block].wids[s.warp];
                        let rank = (wid + h[WARPS] - self.rr_collect[sm][path]) % h[WARPS];
                        if candidate.is_none_or(|x| rank < x.0) {
                            candidate = Some((rank, st, ready, wid));
                        }
                    }
                }
                let Some((_, st, r, wid)) = candidate else {
                    continue;
                };
                let collector = if path == 1 && demux {
                    second.unwrap()
                } else {
                    free
                };
                debug_assert!(first <= collector);
                let id = self.streams[st].ops[self.streams[st].pc];
                let o = &self.ops[id];
                let accept = max(r, self.clock);
                let mut operands = accept + 1;
                for (i, &reg) in o.sources.iter().enumerate() {
                    let bank = (wid + reg % 256) % h[RFB];
                    let t = self
                        .b
                        .reserve(Key(14, sm, reg / 256, bank as u64), accept, 1, h[RFR]);
                    operands = if i == 0 { t + 3 } else { max(operands, t + 3) };
                }
                let token = Token {
                    op: id,
                    sm,
                    wid,
                    time: operands,
                };
                self.collectors[sm][collector] = Some(token);
                self.streams[st].pc += 1;
                self.streams[st].busy = true;
                for &dst in o.dest.iter().chain(o.extra_dests.iter()) {
                    if dst != 256 {
                        self.streams[st].regs[dst] = id;
                    }
                }
                self.b.stats[5 + o.kind] += 1;
                self.schedule(token, 0, collector);
                self.rr_collect[sm][path] = (wid + 1) % h[WARPS];
            }
        }
    }
    fn retire(&mut self, token: Token, time: Time) {
        let o = &self.ops[token.op];
        self.completion[token.op] = Some(time);
        let block = o.block;
        if o.kind == STORE {
            self.written.extend(
                o.addresses
                    .iter()
                    .filter(|a| **a < 0x70000000 || **a >= 0x70000000 + self.b.hw[LDS] as u64)
                    .map(|a| a / self.b.hw[LINE] as u64 * self.b.hw[LINE] as u64),
            );
        }
        if o.kind == LOAD || o.kind == STORE {
            self.lsu_count[token.sm] -= 1;
            self.lsu_warp[token.sm][token.wid] -= 1;
        }
        let b = &mut self.blocks[block];
        b.retired += 1;
        b.end = max(b.end, time);
        if b.retired == b.ops {
            let sm = b.sm.take().unwrap();
            self.sm_release[sm] = b.end;
            self.end = max(self.end, b.end);
            self.sm_blocks[sm] -= 1;
            self.resident_streams[sm].retain(|st| self.streams[*st].block != block);
            for &w in &b.wids {
                self.warp_free[sm][w] = true;
            }
            if self.recipe.is_some() {
                for &st in &b.streams {
                    self.streams[st].ops.clear();
                    self.streams[st].pc = 0;
                    self.register_buffers
                        .push(std::mem::take(&mut self.streams[st].regs));
                    self.index_buffers
                        .push(std::mem::take(&mut self.streams[st].ops));
                }
                for id in b.live.drain(..) {
                    self.ops[id].addresses.clear();
                    self.ops[id].sources.clear();
                    self.ops[id].deps.clear();
                    self.free_ops.push(id);
                }
                self.index_buffers.push(std::mem::take(&mut b.live));
            }
        }
    }
    fn writebacks(&mut self) -> Vec<bool> {
        let h = self.b.hw;
        let mut consumed = std::mem::take(&mut self.consumed_scratch);
        consumed.resize(self.pipes.len(), false);
        consumed.fill(false);
        let mut candidates = std::mem::take(&mut self.wb_scratch);
        let mut banks = std::mem::take(&mut self.wb_banks);
        for sm in 0..h[SMS] {
            candidates.clear();
            for &p in &self.sm_pipes[sm] {
                let pipe = &self.pipes[p];
                if [FADD, FMA].contains(&pipe.kind) {
                    continue;
                }
                if let Some(t) = pipe.output() {
                    let kind = self.ops[t.op].kind;
                    let priority = match kind {
                        SCALAR | VECTOR | SHUFFLE => 0,
                        LOAD => 2,
                        TENSOR | MMA_BF16 | MMA_F16 | MMA_TF32 => 5,
                        _ => 1,
                    };
                    let second = match kind {
                        FMAX => 1,
                        FTOI => 3,
                        ITOF => 4,
                        _ => 0,
                    };
                    candidates.push((priority, second, Some(p), t));
                }
            }
            if let Some(&t) = self.lsu_output[sm].front() {
                candidates.push((2, 0, None, t));
            }
            candidates.sort_by(|a, b| {
                let key = |p: Option<usize>| {
                    p.map(|i| self.pipes[i].arbitration_key.as_str())
                        .unwrap_or("None")
                };
                (a.0, a.1, key(a.2)).cmp(&(b.0, b.1, key(b.2)))
            });
            let mut ports = [0usize; 2];
            banks.fill([0, 0]);
            let mut fpu = false;
            for index in 0..candidates.len() {
                let (_, _, p, t) = candidates[index];
                let o = &self.ops[t.op];
                let path = o.dest.map(|r| r / 256).unwrap_or(0);
                if fpu && Self::fpu(o.kind) {
                    self.b.stats[WB_STALL] += 1;
                    continue;
                }
                let registers = if o.dest.is_some() {
                    1 + o.extra_dests.len()
                } else {
                    1
                };
                let mut progress = self.wb_progress[t.op];
                while progress < registers {
                    let reg = if progress == 0 {
                        o.dest.unwrap_or(0)
                    } else {
                        o.extra_dests[progress - 1]
                    };
                    let bank = (t.wid + reg % 256) % h[RFB];
                    if ports[path] >= h[WB] || banks[bank][path] >= h[RFW] {
                        break;
                    }
                    ports[path] += 1;
                    banks[bank][path] += 1;
                    progress += 1;
                }
                self.wb_progress[t.op] = progress;
                if progress < registers {
                    self.b.stats[WB_STALL] += 1;
                    continue;
                }
                let done = max(t.time, self.clock);
                assert_eq!(done, self.clock, "writeback future");
                fpu |= Self::fpu(o.kind);
                if let Some(p) = p {
                    consumed[p] = true;
                } else {
                    self.lsu_output[sm].pop_front();
                }
                self.retire(t, done);
            }
        }
        self.wb_scratch = candidates;
        self.wb_banks = banks;
        consumed
    }
    fn address(&mut self) {
        let h = self.b.hw;
        for sm in 0..h[SMS] {
            let Some(t) = self.lsu_buffer[sm] else {
                continue;
            };
            if self.address_until[sm] > self.clock || self.lsu_count[sm] > h[LSU] {
                continue;
            }
            let start = max(t.time, self.clock);
            let done = self.b.memory(start, &self.ops[t.op], sm, t.wid);
            self.address_until[sm] = self.b.last(Key(9, sm, 0, 0));
            self.lsu_buffer[sm] = None;
            self.schedule(
                Token { time: done, ..t },
                if self.ops[t.op].dest.is_some() { 1 } else { 2 },
                0,
            );
        }
    }
    fn fpu_transfer(&mut self, consumed: &mut Vec<bool>) -> Vec<Option<Token>> {
        let mut incoming = std::mem::take(&mut self.transfer_scratch);
        incoming.resize(self.pipes.len(), None);
        incoming.fill(None);
        for sm in 0..self.b.hw[SMS] {
            let waiting = [FMA, FADD].map(|kind| {
                self.pipe_ids[sm][kind]
                    .first()
                    .copied()
                    .filter(|&p| self.pipes[p].output().is_some())
            });
            let Some(source) = waiting[0].or(waiting[1]) else {
                continue;
            };
            let waiting_count = waiting.iter().filter(|x| x.is_some()).count();
            let target = self.pipe(sm, FPADD, 0);
            if !self.pipes[target].input_ready(consumed.get(target).copied().unwrap_or(false)) {
                self.b.stats[FPU_BACK] += waiting_count as u64;
                continue;
            }
            let t = self.pipes[source].output().unwrap();
            incoming.resize(self.pipes.len(), None);
            consumed.resize(self.pipes.len(), false);
            incoming[target] = Some(Token {
                time: max(t.time, self.clock),
                ..t
            });
            consumed[source] = true;
            if waiting_count > 1 {
                self.b.stats[FPU_ARB] += 1;
            }
        }
        incoming
    }
    fn issue(&mut self, consumed: &[bool]) -> Vec<Option<Token>> {
        let h = self.b.hw;
        let mut incoming = std::mem::take(&mut self.issue_scratch);
        incoming.resize(self.pipes.len(), None);
        incoming.fill(None);
        for sm in 0..h[SMS] {
            for path in [1, 0] {
                let mut available: Option<(usize, usize, Token, Option<usize>)> = None;
                for index in 0..self.issue_ready[sm][path].len() {
                    let (c, t) = self.issue_ready[sm][path][index];
                    let kind = self.ops[t.op].kind;
                    let mut target = None;
                    if kind == LOAD || kind == STORE {
                        if self.lsu_buffer[sm].is_some() || self.lsu_warp[sm][t.wid] >= h[LSUW] {
                            continue;
                        }
                    } else if kind != BARRIER {
                        let count = if kind == TENSOR || (MMA_BF16..=MMA_TF32).contains(&kind) {
                            h[TU]
                        } else {
                            1
                        };
                        for i in 0..count {
                            if (kind == TENSOR || (MMA_BF16..=MMA_TF32).contains(&kind))
                                && self.tensor_next[sm][i] > self.clock
                            {
                                continue;
                            }
                            let p = self.pipe(sm, kind, i);
                            if self.pipes[p].next_accept <= self.clock
                                && self.pipes[p]
                                    .input_ready(consumed.get(p).copied().unwrap_or(false))
                                && incoming.get(p).is_none_or(|x| x.is_none())
                            {
                                target = Some(p);
                                break;
                            }
                        }
                        if target.is_none() {
                            self.b.stats[EXEC_STALL] += 1;
                            continue;
                        }
                    }
                    let rank = (c + h[COL] - self.rr_issue[sm][path]) % h[COL];
                    if available.is_none_or(|a| rank < a.0) {
                        available = Some((rank, c, t, target));
                    }
                }
                let Some((_, c, t, target)) = available else {
                    continue;
                };
                let issue = max(t.time, self.clock);
                let st = self.op_stream[t.op];
                self.streams[st].last_issue = Some(issue);
                self.streams[st].busy = false;
                self.collectors[sm][c] = None;
                self.issue_ready[sm][path].retain(|(i, _)| *i != c);
                self.rr_issue[sm][path] = (c + 1) % h[COL];
                let kind = self.ops[t.op].kind;
                if kind == LOAD || kind == STORE {
                    self.lsu_count[sm] += 1;
                    self.lsu_warp[sm][t.wid] += 1;
                    self.lsu_buffer[sm] = Some(Token { time: issue, ..t });
                } else if kind == BARRIER {
                    let block = self.ops[t.op].block;
                    let done = max(issue, self.blocks[block].end);
                    for s in &mut self.streams {
                        if s.block == block {
                            s.last_issue = Some(done);
                        }
                    }
                    self.retire(t, done);
                } else {
                    let target = target.unwrap();
                    self.pipes[target].next_accept = issue + self.pipes[target].interval;
                    if kind == TENSOR || (MMA_BF16..=MMA_TF32).contains(&kind) {
                        self.tensor_next[sm][self.pipes[target].unit] =
                            self.pipes[target].next_accept;
                    }
                    incoming.resize(self.pipes.len(), None);
                    incoming[target] = Some(Token { time: issue, ..t });
                }
            }
        }
        incoming
    }
    fn advance(&mut self, incoming: Vec<Option<Token>>, consumed: Vec<bool>) {
        for (p, pipe) in self.pipes.iter_mut().enumerate() {
            if incoming.get(p).is_none_or(|x| x.is_none()) && pipe.occupied == 0 {
                continue;
            }
            let mut next_ready = consumed.get(p).copied().unwrap_or(false);
            let input_ready = pipe.input_ready(next_ready);
            if next_ready && pipe.output().is_some() {
                pipe.occupied -= 1;
            }
            if incoming.get(p).is_some_and(|x| x.is_some()) {
                pipe.occupied += 1;
            }
            if next_ready || pipe.output().is_none() {
                // With a free output every elastic stage advances. Rotate the
                // ring in O(1); consumers normalize token time to this clock.
                pipe.stages.pop_back();
                pipe.stages
                    .push_front(incoming.get(p).copied().flatten().map(|t| Token {
                        time: self.clock + 1,
                        ..t
                    }));
                assert!(incoming.get(p).is_none_or(|x| x.is_none()) || input_ready);
                continue;
            }
            for i in (0..pipe.stages.len()).rev() {
                next_ready |= pipe.stages[i].is_none();
                if next_ready {
                    let t = if i == 0 {
                        incoming.get(p).copied().flatten()
                    } else {
                        pipe.stages[i - 1]
                    };
                    pipe.stages[i] = t.map(|t| Token {
                        time: self.clock + 1,
                        ..t
                    });
                }
            }
            assert!(incoming.get(p).is_none_or(|x| x.is_none()) || input_ready);
        }
        self.transfer_scratch = incoming;
        self.consumed_scratch = consumed;
    }
    fn run(mut self) -> [u64; RESULT_LEN] {
        while !self.waiting.is_empty() || self.sm_blocks.iter().any(|n| *n > 0) {
            if self.clock % 128 == 0 {
                self.b.prune(self.clock);
            }
            while self.pending.peek().is_some_and(|p| p.0.time <= self.clock) {
                let p = self.pending.pop().unwrap().0;
                let t = Token {
                    op: p.op,
                    sm: p.sm,
                    wid: p.wid,
                    time: p.time,
                };
                match p.action {
                    0 => {
                        let path = self.path(p.op);
                        self.issue_ready[p.sm][path].push((p.collector, t));
                    }
                    1 => self.lsu_output[p.sm].push_back(t),
                    2 => self.retire(t, t.time),
                    _ => unreachable!(),
                }
            }
            let mut consumed = self.writebacks();
            self.allocate();
            self.address();
            let mut incoming = self.fpu_transfer(&mut consumed);
            let issued = self.issue(&consumed);
            incoming.resize(self.pipes.len(), None);
            for (index, token) in issued.iter().copied().enumerate() {
                if token.is_some() {
                    assert!(incoming[index].is_none());
                    incoming[index] = token;
                }
            }
            self.issue_scratch = issued;
            self.address();
            self.collect();
            let issuing = incoming.iter().any(|x| x.is_some());
            self.advance(incoming, consumed);
            self.clock += 1;
            self.b.stats[3] += 1;
            // No arrivals, issue slots, outputs or ready warp can change until
            // the first pending event or token reaches a pipeline output. Every
            // elastic stage shifts freely over this interval (no downstream
            // output is reached before the endpoint), preserving backpressure.
            if self.b.target[5] == 1
                && !issuing
                && self.lsu_buffer.iter().all(|x| x.is_none())
                && self.lsu_output.iter().all(|q| q.is_empty())
                && self
                    .issue_ready
                    .iter()
                    .all(|p| p.iter().all(|q| q.is_empty()))
                && self.pipes.iter().all(|p| p.output().is_none())
            {
                let mut blocked = true;
                for sm in 0..self.resident_streams.len() {
                    for index in 0..self.resident_streams[sm].len() {
                        let st = self.resident_streams[sm][index];
                        if self.ready(st).is_some() {
                            blocked = false;
                            break;
                        }
                    }
                    if !blocked {
                        break;
                    }
                }
                if blocked {
                    let mut next = self.pending.peek().map(|p| p.0.time).unwrap_or(u64::MAX);
                    for pipe in &self.pipes {
                        if let Some(stage) = pipe.stages.iter().rposition(|s| s.is_some()) {
                            next = next.min(self.clock + (pipe.stages.len() - 1 - stage) as u64);
                        }
                    }
                    if next > self.clock && next < u64::MAX {
                        let skip = (next - self.clock) as usize;
                        for pipe in &mut self.pipes {
                            if pipe.occupied > 0 {
                                // No live token leaves this pipeline before next.
                                for index in (0..pipe.stages.len()).rev() {
                                    pipe.stages[index] = if index >= skip {
                                        pipe.stages[index - skip].map(|t| Token { time: next, ..t })
                                    } else {
                                        None
                                    };
                                }
                            }
                        }
                        self.b.stats[4] += (next - self.clock) as u64;
                        self.clock = next;
                    }
                }
            }
        }
        let dirty: Vec<_> = self
            .b
            .cache
            .l1
            .values()
            .flat_map(|q| q.iter())
            .filter(|t| t.dirty)
            .map(|t| (t.line, t.fill))
            .collect();
        for (line, fill) in dirty {
            self.b.transfer(max(self.end, fill), line, true);
        }
        self.b.stats[0] = max(self.end, self.b.writes);
        for q in self
            .b
            .cache
            .l1
            .values_mut()
            .chain(self.b.cache.l2.values_mut())
        {
            q.retain(|t| !self.written.contains(&t.line));
            for t in q {
                t.fill = 0;
                t.dirty = false;
            }
        }
        self.b.stats
    }
}
struct Reader<'a> {
    data: &'a [u64],
    at: usize,
}
impl Reader<'_> {
    fn get(&mut self) -> usize {
        let v = *self.data.get(self.at).expect("truncated compact stream");
        self.at += 1;
        usize::try_from(v).unwrap()
    }
    fn list(&mut self, n: usize) -> Vec<usize> {
        assert!(n <= self.data.len() - self.at);
        (0..n).map(|_| self.get()).collect()
    }
}
struct Session {
    hw: [usize; 32],
    intervals: Vec<u64>,
    cache: Cache,
    result: [u64; RESULT_LEN],
    error: Vec<u8>,
    snapshot: Vec<u64>,
    generated: Vec<u64>,
    target: [u64; 10],
}
impl Session {
    fn execute(&mut self, data: &[u64]) {
        let mut r = Reader { data, at: 0 };
        let abi = r.get();
        assert!((0x56545337..=0x56545339).contains(&abi), "compact ABI");
        let n = r.get();
        assert!(n > 0 && n <= data.len());
        let wpb = r.get();
        assert!(wpb > 0 && wpb <= self.hw[WARPS]);
        let vgpr = r.get();
        let sgpr = r.get();
        let lds = r.get();
        let mut ops = Vec::with_capacity(n);
        for i in 0..n {
            let kind = r.get();
            assert!(kind <= SHUFFLE && kind != FPADD);
            let block = r.get();
            let warp = r.get();
            assert!(warp < wpb);
            let destination_field = r.get();
            let ns = r.get();
            let na = r.get();
            let nd = r.get();
            let width = if abi >= 0x56545338 { r.get() } else { 4 };
            let active_mask = if abi == 0x56545339 {
                r.get() as u64
            } else {
                (1u64 << self.hw[3]) - 1
            };
            assert!(active_mask < (1u64 << self.hw[3]));
            assert!([1, 2, 4].contains(&width));
            let destinations = if abi >= 0x56545338 {
                r.list(destination_field)
            } else if destination_field == NONE {
                Vec::new()
            } else {
                vec![destination_field]
            };
            let dest = destinations.first().copied().unwrap_or(NONE);
            let extra_dests = destinations.iter().skip(1).copied().collect();
            let sources = r.list(ns);
            assert!(sources.iter().all(|x| *x < 512));
            assert!(dest == NONE || dest < 512);
            let addresses: Vec<u64> = r.list(na).into_iter().map(|a| a as u64).collect();
            if kind == LOAD || kind == STORE {
                assert!(!addresses.is_empty() && addresses.len() <= self.hw[3]);
                assert!(addresses
                    .iter()
                    .all(|a| *a < (1u64 << 32) && a % width as u64 == 0));
                assert!((kind == LOAD && dest != NONE) || (kind == STORE && dest == NONE));
                let shared = |a: u64| a >= 0x70000000 && a < 0x70000000 + self.hw[LDS] as u64;
                assert!(addresses.iter().all(|a| shared(*a) == shared(addresses[0])));
            } else {
                assert!(addresses.is_empty());
            }
            if kind == BARRIER {
                assert!(sources.is_empty() && dest == NONE);
            }
            let deps = r.list(nd);
            assert!(deps.iter().all(|d| *d < i));
            ops.push(Op {
                kind,
                block,
                warp,
                sources,
                dest: if dest == NONE { None } else { Some(dest) },
                addresses,
                deps,
                extra_dests,
                width,
                active_mask,
            });
        }
        assert_eq!(r.at, data.len());
        let b = Builder::new(&self.hw, &mut self.cache, &self.intervals, &self.target);
        self.result = Engine::new(b, ops, wpb, vgpr, sgpr, lds).run();
    }
    fn state(&mut self) {
        let mut data = vec![0x56545337, self.cache.lfsr as u64];
        let mut l1: Vec<_> = self
            .cache
            .l1
            .iter()
            .filter(|(_, v)| !v.is_empty())
            .collect();
        l1.sort_by_key(|(k, _)| **k);
        data.push(l1.len() as u64);
        for ((sm, set), tags) in l1 {
            data.extend([*sm as u64, *set as u64, tags.len() as u64]);
            for t in tags {
                data.extend([t.line, t.way as u64]);
            }
        }
        let mut l2: Vec<_> = self
            .cache
            .l2
            .iter()
            .filter(|(_, v)| !v.is_empty())
            .collect();
        l2.sort_by_key(|(k, _)| **k);
        data.push(l2.len() as u64);
        for (set, tags) in l2 {
            data.extend([*set as u64, tags.len() as u64]);
            for t in tags {
                data.extend([t.line, t.way as u64]);
            }
        }
        self.snapshot = data;
    }
    fn restore(&mut self, data: &[u64]) {
        let mut r = Reader { data, at: 0 };
        assert_eq!(r.get(), 0x56545337);
        let mut cache = Cache::default();
        cache.lfsr = r.get().try_into().unwrap();
        let n = r.get();
        assert!(n <= self.hw[SMS] * self.hw[L1S]);
        for _ in 0..n {
            let sm = r.get();
            let set = r.get();
            assert!(sm < self.hw[SMS] && set < self.hw[L1S]);
            let count = r.get();
            assert!(count <= self.hw[L1W]);
            let mut tags = VecDeque::new();
            for _ in 0..count {
                let line = r.get() as u64;
                let way = r.get();
                assert!(line < (1u64 << 32) && line % self.hw[LINE] as u64 == 0);
                assert_eq!(
                    line / self.hw[LINE] as u64 % self.hw[L1S] as u64,
                    set as u64
                );
                assert!(way < self.hw[L1W] && !tags.iter().any(|t: &Tag| t.line == line));
                tags.push_back(Tag {
                    line,
                    way,
                    fill: 0,
                    dirty: false,
                });
            }
            assert!(cache.l1.insert((sm, set), tags).is_none());
        }
        let n = r.get();
        assert!(n <= self.hw[L2S]);
        for _ in 0..n {
            let set = r.get();
            assert!(set < self.hw[L2S]);
            let count = r.get();
            assert!(count <= self.hw[L2W]);
            let mut tags = VecDeque::new();
            for _ in 0..count {
                let line = r.get() as u64;
                let way = r.get();
                assert!(way < self.hw[L2W]);
                assert!(line < (1u64 << 32) && line % self.hw[LINE] as u64 == 0);
                assert_eq!(
                    line / self.hw[LINE] as u64 % self.hw[L2S] as u64,
                    set as u64
                );
                assert!(!tags.iter().any(|t: &Tag| t.line == line || t.way == way));
                tags.push_back(Tag {
                    line,
                    way,
                    fill: 0,
                    dirty: false,
                });
            }
            assert!(cache.l2.insert(set, tags).is_none());
        }
        assert_eq!(r.at, data.len());
        self.cache = cache;
    }
}
#[no_mangle]
pub unsafe extern "C" fn vt_create(hw: *const u64, intervals: *const u64, n: usize) -> *mut c_void {
    catch_unwind(|| {
        let raw = slice::from_raw_parts(hw, 32);
        let mut h = [0usize; 32];
        for i in 0..32 {
            h[i] = raw[i] as usize;
            assert!(h[i] > 0);
        }
        assert!(n > 0);
        let s = Session {
            hw: h,
            intervals: slice::from_raw_parts(intervals, n).to_vec(),
            cache: Cache::default(),
            result: [0; RESULT_LEN],
            error: Vec::new(),
            snapshot: Vec::new(),
            generated: Vec::new(),
            target: [0, 0, 0, 0, 0, 1, 0, 0, 0, 0],
        };
        Box::into_raw(Box::new(s)) as *mut c_void
    })
    .unwrap_or(std::ptr::null_mut())
}
#[no_mangle]
pub unsafe extern "C" fn vt_destroy(p: *mut c_void) {
    if !p.is_null() {
        drop(Box::from_raw(p as *mut Session));
    }
}
#[no_mangle]
pub unsafe extern "C" fn vt_run(p: *mut c_void, data: *const u64, n: usize, out: *mut u64) -> i32 {
    let s = &mut *(p as *mut Session);
    let result = catch_unwind(AssertUnwindSafe(|| {
        s.execute(slice::from_raw_parts(data, n))
    }));
    if result.is_err() {
        s.error = b"invalid compact program or timing invariant".to_vec();
        return -1;
    }
    std::ptr::copy_nonoverlapping(s.result.as_ptr(), out, RESULT_LEN);
    0
}
#[no_mangle]
pub unsafe extern "C" fn vt_state(p: *mut c_void, n: *mut usize) -> *const u64 {
    let s = &mut *(p as *mut Session);
    s.state();
    *n = s.snapshot.len();
    s.snapshot.as_ptr()
}
#[no_mangle]
pub unsafe extern "C" fn vt_restore(p: *mut c_void, data: *const u64, n: usize) -> i32 {
    let s = &mut *(p as *mut Session);
    if catch_unwind(AssertUnwindSafe(|| {
        s.restore(slice::from_raw_parts(data, n))
    }))
    .is_err()
    {
        return -1;
    }
    0
}

#[no_mangle]
pub unsafe extern "C" fn vt_generate(
    p: *mut c_void,
    words: *const u32,
    nw: usize,
    launch: *const u64,
    nl: usize,
    n: *mut usize,
) -> *const u64 {
    let s = &mut *(p as *mut Session);
    *n = 0;
    let result = catch_unwind(AssertUnwindSafe(|| {
        let launch = slice::from_raw_parts(launch, nl);
        provider::generate(slice::from_raw_parts(words, nw), launch)
            .map(|ops| provider::compact(&ops, launch))
    }));
    match result {
        Ok(Ok(data)) => {
            s.generated = data;
            *n = s.generated.len();
            s.generated.as_ptr()
        }
        Ok(Err(error)) => {
            s.error = error.into_bytes();
            std::ptr::null()
        }
        Err(_) => {
            s.error = b"invalid binary provider input".to_vec();
            std::ptr::null()
        }
    }
}
#[no_mangle]
pub unsafe extern "C" fn vt_error(p: *mut c_void, n: *mut usize) -> *const u8 {
    let s = &mut *(p as *mut Session);
    *n = s.error.len();
    s.error.as_ptr()
}

#[no_mangle]
pub unsafe extern "C" fn vt_run_program(
    p: *mut c_void,
    words: *const u32,
    nw: usize,
    launch: *const u64,
    nl: usize,
    out: *mut u64,
) -> i32 {
    let s = &mut *(p as *mut Session);
    let result = catch_unwind(AssertUnwindSafe(|| {
        let launch = slice::from_raw_parts(launch, nl).to_vec();
        assert!(launch.len() >= 20);
        let b = Builder::new(&s.hw, &mut s.cache, &s.intervals, &s.target);
        s.result = Engine::streaming(b, slice::from_raw_parts(words, nw).to_vec(), launch).run();
    }));
    if let Err(error) = result {
        s.error = error
            .downcast_ref::<String>()
            .cloned()
            .or_else(|| error.downcast_ref::<&str>().map(|s| s.to_string()))
            .unwrap_or_else(|| "streaming program execution failed".into())
            .into_bytes();
        return -1;
    }
    std::ptr::copy_nonoverlapping(s.result.as_ptr(), out, RESULT_LEN);
    0
}

#[no_mangle]
pub unsafe extern "C" fn vt_target(p: *mut c_void, target: *const u64) -> i32 {
    let s = &mut *(p as *mut Session);
    let values = slice::from_raw_parts(target, 10);
    if values[0] != 1
        || [1, 2, 3, 4, 6, 7, 8, 9]
            .into_iter()
            .any(|i| values[i] == 0 || values[i] > 256)
    {
        return -1;
    }
    s.target.copy_from_slice(values);
    0
}

#[no_mangle]
pub unsafe extern "C" fn vt_fast(p: *mut c_void, enabled: u64) {
    let s = &mut *(p as *mut Session);
    s.target[5] = u64::from(enabled != 0);
}
