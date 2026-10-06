#!/usr/bin/env bash
set -euo pipefail
source ${REMOTE_ENVIRONMENT_SCRIPT}
TASK_ROOT="${VENTUS_FLOW_ROOT:-${REMOTE_FLOW_ROOT}}"
SYNTH_DIR="$TASK_ROOT/evidence/scalar-alu-synthesis-v2"
mkdir "$SYNTH_DIR"
cd "$SYNTH_DIR"
python3 - <<'PY'
import hashlib
import json
import re
from pathlib import Path

source = Path('${REMOTE_PROJECT_ROOT}/sim-verilator/dut.v')
module = re.search(r'^module ScalarALU\(.*?^endmodule', source.read_text(), re.M | re.S)
assert module is not None
Path('ScalarALU.v').write_text(module[0] + '\n')
libraries = sorted(Path('${REMOTE_LIBERTY_ROOT}').glob('asap7sc7p5t_*RVT_TT*.lib'))
cells = []
for library in libraries:
    content = library.read_text()
    for match in re.finditer(r'\bcell\s*\([^)]*\)\s*\{', content):
        depth, quoted, escaped = 1, False, False
        index = match.end()
        while depth:
            char = content[index]
            if escaped:
                escaped = False
            elif char == '\\' and quoted:
                escaped = True
            elif char == '"':
                quoted = not quoted
            elif not quoted:
                depth += (char == '{') - (char == '}')
            index += 1
        cells.append(content[match.start():index])
assert libraries and cells
# This derived Liberty is only a mapper input; STA reads the original libraries.
header = libraries[0].read_text()
first_cell = re.search(r'\bcell\s*\([^)]*\)\s*\{', header)
assert first_cell is not None
Path('mapping.lib').write_text(header[:first_cell.start()] + '\n'.join(cells) + '\n}\n')
manifest = {'top': 'ScalarALU', 'rtl_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'libraries_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in libraries},
            'mapped_cell_definitions': len(cells), 'scope': 'combinational module, no routing or SRAM'}
Path('manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
Path('sta.tcl').write_text('\n'.join(f'read_liberty {p}' for p in libraries) + '''
read_verilog ScalarALU_mapped.v
link_design ScalarALU
create_clock -name virtual_clock -period 1000
set_input_delay 0 -clock virtual_clock [all_inputs]
set_output_delay 0 -clock virtual_clock [all_outputs]
set_load 1 [all_outputs]
report_units
report_checks -path_delay max -format full_clock_expanded -digits 4
exit
''')
PY
yosys -Q -l yosys.log -p 'read_verilog -sv ScalarALU.v; hierarchy -check -top ScalarALU; synth -top ScalarALU -noabc; abc -liberty mapping.lib; clean; tee -o statistics.json stat -json -liberty mapping.lib; write_verilog -noattr ScalarALU_mapped.v' > stdout.log 2> stderr.log
sta -exit sta.tcl > sta.log 2> sta.stderr.log
yosys -Q -l equivalence.log -p 'read_verilog ScalarALU.v; rename ScalarALU gold; read_liberty -ignore_miss_func mapping.lib; read_verilog ScalarALU_mapped.v; proc; flatten ScalarALU; equiv_make gold ScalarALU equiv; hierarchy -top equiv; equiv_simple; equiv_status -assert' > equivalence.stdout.log 2> equivalence.stderr.log
