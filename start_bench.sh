#!/bin/bash
# Script to start bench from erpnext_extensions directory
cd "$(dirname "$0")/../../.." || exit 1
bench start
