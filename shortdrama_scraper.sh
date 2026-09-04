#!/bin/bash

# Change to project directory
cd /home/nativesol/nsreel || exit 1

# Activate virtual environment
source .venv/bin/activate

# Run scraper
python shortdrama_scraper.py

# Deactivate virtual environment
deactivate
