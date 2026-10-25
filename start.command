#!/bin/zsh
# Doppelklick startet das Kanban-Board und öffnet http://localhost:8814
cd "$(dirname "$0")"
python3 server.py
