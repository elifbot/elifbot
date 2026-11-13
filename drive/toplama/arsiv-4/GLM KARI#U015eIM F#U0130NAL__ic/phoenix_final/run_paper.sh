#!/usr/bin/env bash
# PHOENIX FINAL — paper (dry) canlı oturumu: 30 dakika koşar, sonunda rapor yazar.
# Kullanım: ./run_paper.sh [dakika]
MIN=${1:-30}
python3 -m phoenix.main live --engine dry --minutes "$MIN"
