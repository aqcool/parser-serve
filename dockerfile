ARG BASE_IMAGE=quay.io/sclorg/python-312-c9s:c9s

ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.8.19

FROM ${BASE_IMAGE} AS base