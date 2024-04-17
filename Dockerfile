# This Dockerfile is used to generate the docker image dsarchive/histomicstk
# This docker image includes the HistomicsTK python package along with its
# dependencies.
#
# All plugins of HistomicsTK should derive from this docker image

FROM python:3.11

LABEL maintainer="Sam Border - Computational Microscopy Imaging Lab. <samuel.border@medicine.ufl.edu>"

RUN apt-get update && \
    apt-get autoremove && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    wget \
    curl \
    ca-certificates \
    libcurl4-openssl-dev \
    libexpat1-dev \
    unzip \
    libhdf5-dev \
    software-properties-common \
    libssl-dev \
    # Standard build tools \
    build-essential \
    cmake \
    autoconf \
    automake \
    libtool \
    pkg-config \
    libmemcached-dev && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN apt-get update ##[edited]

RUN apt-get install libxml2-dev libxslt1-dev -y

# Required for opencv-python (cv2)
RUN apt-get update && apt-get install ffmpeg libsm6 libxext6 -y

WORKDIR /

RUN which  python && \
    python --version

ENV build_path=$PWD/build
ENV PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

# Copying location of feature extraction scripts
ENV ann_hierarchy_path=$PWD/ann_hierarchy
RUN mkdir -p $ann_hierarchy_path

RUN apt-get update && \
    apt-get install -y --no-install-recommends memcached && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY . $ann_hierarchy_path/
WORKDIR $ann_hierarchy_path

#   Upgrade setuptools, as the version in Conda won't upgrade cleanly unless it
# is ignored.

# Installing packages in setup.py
RUN pip install --no-cache-dir --upgrade --ignore-installed pip setuptools && \
    pip install --no-cache-dir .  && \
    rm -rf /root/.cache/pip/*

# Show what was installed
RUN python --version && pip --version && pip freeze

# define entrypoint through which all CLIs can be run
WORKDIR $ann_hierarchy_path/ann_hierarchy/cli
# Test our entrypoint.  If we have incompatible versions of numpy and
# openslide, one of these will fail
RUN python -m slicer_cli_web.cli_list_entrypoint --list_cli
RUN python -m slicer_cli_web.cli_list_entrypoint AnnotationHierarchy --help
RUN python -m slicer_cli_web.cli_list_entrypoint CreateTissueAnnotation --help


ENTRYPOINT ["/bin/bash", "docker-entrypoint.sh"]
