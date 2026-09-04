#!/bin/bash

# Change to project directory
cd /home/nativesol/nsreels || exit 1

# Activate virtual environment
source .venv/bin/activate

# Run scraper
python refresh_episodes.py

# Deactivate virtual environment
deactivate