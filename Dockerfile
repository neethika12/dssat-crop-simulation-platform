# Builds the real DSSAT-CSM Fortran engine from source and serves the
# validation/calibration API on top of it. See docs/BUILD.md for the
# equivalent manual steps this automates.

FROM debian:bookworm-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gfortran cmake make git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --depth 1 https://github.com/DSSAT/dssat-csm-os.git dssat-csm-src
RUN git clone --depth 1 https://github.com/DSSAT/dssat-csm-data.git dssat-data

RUN cmake -S dssat-csm-src -B dssat-csm-src/build \
        -DCMAKE_Fortran_COMPILER=gfortran -DCMAKE_BUILD_TYPE=Release \
    && cmake --build dssat-csm-src/build -j"$(nproc)"

# Assemble a DSSAT install directory (bin + static reference data). Soil,
# Weather and Maize come from the real example-data repo.
RUN mkdir -p dssat_home/bin \
    && cp dssat-csm-src/build/bin/dscsm048 dssat_home/bin/ \
    && cp dssat-csm-src/Data/*.CDE dssat_home/ \
    && cp dssat-csm-src/Data/DSCSM048.CTR dssat_home/ \
    && cp -r dssat-csm-src/Data/StandardData dssat_home/ \
    && cp -r dssat-csm-src/Data/Genotype dssat_home/ \
    && cp -r dssat-csm-src/Data/Pest dssat_home/ \
    && cp -r dssat-data/Soil dssat_home/Soil \
    && cp -r dssat-data/Weather dssat_home/Weather \
    && cp -r dssat-data/Maize dssat_home/Maize


FROM python:3.11-slim

# libgfortran is needed at runtime for the compiled Fortran binary even
# though we're not compiling in this stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgfortran5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=build /src/dssat_home ./dssat_home
COPY --from=build /src/dssat-data/Maize ./dssat-data/Maize

COPY pyproject.toml ./
COPY dssat_validator ./dssat_validator
COPY webapp ./webapp
RUN pip install --no-cache-dir . fastapi "uvicorn[standard]"

EXPOSE 8420
ENV PORT=8420
CMD ["sh", "-c", "python -m uvicorn webapp.backend.main:app --host 0.0.0.0 --port ${PORT}"]
