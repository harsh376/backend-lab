#!/bin/bash

echo "Configuring PYTHONPATH"
echo $(pwd)
PYTHONPATH=$(pwd); export PYTHONPATH

chmod a+x bin/*

echo "Installing uv"
curl -LsSf https://astral.sh/uv/install.sh | sh

echo "Sync virtual env"
uv sync

echo "Configuring pre-commit hooks"
git config --unset-all core.hooksPath
uv run pre-commit install
