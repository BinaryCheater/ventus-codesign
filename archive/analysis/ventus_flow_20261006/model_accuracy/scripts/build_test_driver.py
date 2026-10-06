"""Create a separate observation-only driver, retaining the official library."""

import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
output = root / "accuracy-driver-v2"
output.mkdir()
source = root / "src/cyclesim/src"
main = (source / "main.cpp").read_text()
# Begin from the upstream file, independently of the previous vecadd test patch.
main = subprocess.check_output(["git", "-C", str(source), "show", "HEAD:src/main.cpp"], text=True)
main = main.replace(
    "#include <cstdint>", "#include <cstdint>\n#include <cstdlib>\n#include <iomanip>"
)
main = main.replace(
    "ventus_cyclesim_get_default_config(&config);",
    "ventus_cyclesim_get_default_config(&config);\n    config.ramulator.enable = false;",
)
needle = "            // to destroy the virtual memory space after the kernel finished"
insert = """            if (const char* count = std::getenv("VENTUS_TEST_WORDS")) {
                std::vector<uint32_t> words(std::stoul(count));
                ventus_cyclesim_vmemcpy_d2h(sim, ptroot, words.data(), 0x90002000, words.size()*4);
                for (unsigned i=0; i<words.size(); ++i)
                    std::cout << "TEST_OUTPUT " << std::dec << i << " " << std::hex << words[i] << std::dec << std::endl;
                std::cout << "TEST_KERNEL_FINISH_NS " << ventus_cyclesim_get_time(sim) << std::endl;
            }
"""
assert main.count(needle) == 1
main = main.replace(needle, insert + needle)
(output / "main.cpp").write_text(main)
build = root / "cyclesim-build"
objects = build / "CMakeFiles/main.dir/src"
command = [
    "/usr/bin/g++",
    "-O2",
    "-std=c++20",
    "-DSPDLOG_FMT_EXTERNAL",
    "-DSPDLOG_ACTIVE_LEVEL=SPDLOG_LEVEL_TRACE",
    "-I" + str(source),
    str(output / "main.cpp"),
]
command += [str(objects / (x + ".cpp.o")) for x in ["cmdarg", "parse_kernel", "task"]]
command += [
    "-L" + str(build),
    "-lVentusCycleSim",
    "-lspdlog",
    "-lfmt",
    "-Wl,-rpath," + str(build),
    "-Wl,-rpath-link," + str(build / "dependencies/ramulator2"),
    "-o",
    str(output / "main"),
]
subprocess.run(command, check=True)
