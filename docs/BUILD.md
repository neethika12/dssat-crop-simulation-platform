# Building the DSSAT-CSM engine

This project drives the **real** DSSAT Cropping System Model (DSSAT-CSM),
not a mock. The public `DSSATTools` PyPI package only ships a precompiled
Linux x86-64 binary, which won't run natively on Apple Silicon (or any
non-Linux host). Instead, this repo compiles DSSAT-CSM from its official
Fortran source directly, targeting whatever platform you're on.

## 1. Prerequisites

- A Fortran compiler: `brew install gcc` (provides `gfortran`) on macOS, or
  `apt install gfortran` on Linux.
- CMake: `brew install cmake` / `apt install cmake`.

## 2. Get the source

```bash
git clone --depth 1 https://github.com/DSSAT/dssat-csm-os.git dssat-csm-src
git clone --depth 1 https://github.com/DSSAT/dssat-csm-data.git dssat-data
```

`dssat-csm-os` is the model's Fortran source. `dssat-csm-data` is DSSAT's
official example-experiment repository — real field-trial datasets (FileX
experiments, weather, soil, and observed-data files) used for validation.
This project uses `dssat-data/Maize/UFGA8201.MZX`, a real 1982 University of
Florida (Gainesville) nitrogen x irrigation maize trial.

## 3. Compile

```bash
cd dssat-csm-src
mkdir build && cd build
cmake -DCMAKE_Fortran_COMPILER=gfortran -DCMAKE_BUILD_TYPE=Release ..
make -j$(nproc || sysctl -n hw.ncpu)
```

This produces `build/bin/dscsm048`, a native executable for your platform.

## 4. Assemble a DSSAT install directory

DSSAT-CSM needs a directory of static reference data (crop-code tables,
genotype/cultivar files, standard data) alongside the executable:

```bash
mkdir -p dssat_home/bin
cp build/bin/dscsm048 dssat_home/bin/
cp dssat-csm-src/Data/*.CDE dssat_home/
cp dssat-csm-src/Data/DSCSM048.CTR dssat_home/
cp -r dssat-csm-src/Data/StandardData dssat_home/
cp -r dssat-csm-src/Data/Genotype dssat_home/
cp -r dssat-csm-src/Data/Pest dssat_home/
ln -s "$(pwd)/dssat-data/Soil" dssat_home/Soil
ln -s "$(pwd)/dssat-data/Weather" dssat_home/Weather
ln -s "$(pwd)/dssat-data/Maize" dssat_home/Maize
```

## 5. The 80-character path limit

DSSAT-CSM's Fortran I/O routines (`InputModule/PATH.for`) use **fixed
80-character path buffers**. An install placed under a long path (this is
common — `/Users/<name>/Desktop/.../dssat_home` easily exceeds 80 chars)
silently overflows the buffer and crashes with:

```
Fortran runtime error: Substring out of bounds: upper bound (89) of 'pathc' exceeds string length (80)
```

`dssat_validator.simulation.engine.SimulationEngine` works around this
automatically: it maintains a short-named symlink under `/tmp` (e.g.
`/tmp/dssat48home`) pointing at the real install directory, generates the
`DSSATPRO.L48` config to reference that short path, and always runs the
model from a short-named scratch working directory under `/tmp`. You don't
need to do anything about this yourself — it's handled transparently by
`SimulationEngine.__init__`.

## 6. Verify

```bash
pip install -e .
pytest tests/test_integration.py -v
```

If `dssat_home/bin/dscsm048` doesn't exist, integration and calibration
tests are skipped automatically rather than failing.
