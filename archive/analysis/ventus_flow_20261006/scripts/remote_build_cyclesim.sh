#!/usr/bin/env bash
set -euo pipefail
source ${REMOTE_ENVIRONMENT_SCRIPT}
TASK_ROOT="${VENTUS_FLOW_ROOT:-${REMOTE_FLOW_ROOT}}"
PREFIX="$TASK_ROOT/deps/install"
mkdir -p "$PREFIX" "$TASK_ROOT/deps/bin"
# The upstream CMake file requires a launcher named ccache; this explicit
# pass-through wrapper permits building without installing a system package.
printf '#!/usr/bin/env bash\nexec "$@"\n' > "$TASK_ROOT/deps/bin/ccache"
chmod +x "$TASK_ROOT/deps/bin/ccache"
export PATH="$TASK_ROOT/deps/bin:$PATH"
export CPATH="$PREFIX/include${CPATH:+:$CPATH}"
export LIBRARY_PATH="$PREFIX/lib${LIBRARY_PATH:+:$LIBRARY_PATH}"
export LD_LIBRARY_PATH="$PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
cd "$TASK_ROOT/deps"
git clone --quiet https://github.com/accellera-official/systemc.git systemc
git -C systemc checkout --quiet 5fc1469339775b54b1fcc2020ac744a58be5b50e
/usr/bin/cmake -S systemc -B systemc-build -DCMAKE_CXX_STANDARD=20 \
  -DCMAKE_CXX_COMPILER=/usr/bin/g++ -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PREFIX/systemc" > systemc-configure.log 2>&1
/usr/bin/cmake --build systemc-build --parallel 4 > systemc-build.log 2>&1
/usr/bin/cmake --install systemc-build > systemc-install.log 2>&1
# The simulator's Linux build expects this specific library directory.
ln -s lib "$PREFIX/systemc/lib-linux64"
git clone --quiet --depth 1 --branch 0.8.0 https://github.com/jbeder/yaml-cpp.git yaml-cpp
/usr/bin/cmake -S yaml-cpp -B yaml-build -DYAML_BUILD_SHARED_LIBS=ON \
  -DYAML_CPP_BUILD_TESTS=OFF -DYAML_CPP_BUILD_TOOLS=OFF \
  -DCMAKE_CXX_COMPILER=/usr/bin/g++ -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$PREFIX" > yaml-configure.log 2>&1
/usr/bin/cmake --build yaml-build --parallel 4 > yaml-build.log 2>&1
/usr/bin/cmake --install yaml-build > yaml-install.log 2>&1
git -C "$TASK_ROOT/src/cyclesim" apply "$TASK_ROOT/cyclesim-test-driver.patch"
/usr/bin/cmake -S "$TASK_ROOT/src/cyclesim" -B "$TASK_ROOT/cyclesim-build" \
  -DCMAKE_CXX_COMPILER=/usr/bin/g++ -DCMAKE_C_COMPILER=/usr/bin/gcc \
  -DCMAKE_BUILD_TYPE=Release -DSYSTEMC_HOME="$PREFIX/systemc" \
  -Dfmt_DIR=/usr/lib/x86_64-linux-gnu/cmake/fmt \
  -Dspdlog_DIR=${REMOTE_SPDLOG_ROOT}/lib/cmake/spdlog \
  -DCMAKE_PREFIX_PATH="$PREFIX;${REMOTE_SPDLOG_ROOT}" \
  -DCMAKE_INSTALL_PREFIX="$TASK_ROOT/install" > cyclesim-configure.log 2>&1
/usr/bin/cmake --build "$TASK_ROOT/cyclesim-build" --target main --parallel 8 > cyclesim-build.log 2>&1
/usr/bin/cmake --install "$TASK_ROOT/cyclesim-build" > cyclesim-install.log 2>&1
