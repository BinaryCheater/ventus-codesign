SHELL := /bin/bash

init:
	git submodule update --init --recursive --progress

bump:
	git submodule foreach git stash
	git submodule update --remote
	git add dependencies

bsp:
	./mill -i mill.bsp.BSP/install

idea:
	./mill -i -j 0 mill.idea.GenIdea/idea

compile:
	./mill -i -j 0 __.compile

test:
	mkdir -p test_run_dir
	./mill -i ventus[6.4.0].tests.testOnly play.AdvancedTest 2>&1 | tee test_run_dir/test.log
	# ./mill -i ventus[6.4.0].tests.testOnly play.AsidTests 2>&1 | tee test_run_dir/test.log 	#for asid test, provide two asid test case

verilog:
	./mill ventus[6.4.0].run

fpga-verilog:
	./mill ventus[6.4.0].runMain circt.stage.ChiselMain --module top.GPGPU_axi_adapter_top --target chirrtl --target-dir gen_fpga_verilog/
	cd gen_fpga_verilog/ && firtool --split-verilog --repl-seq-mem --repl-seq-mem-file=mem.conf -o . GPGPU_axi_adapter_top.fir
	./scripts/gen_sep_mem.sh ./scripts/vlsi_mem_gen gen_fpga_verilog/mem.conf gen_fpga_verilog/

clean:
	rm -rf out/ test_run_dir/ .idea/

clean-git:
	git clean -fd
