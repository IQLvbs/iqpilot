"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import os

collect_ignore_glob = [] if os.environ.get('IQ_LONG_CORPUS') else ['test_corpus_regression.py', 'test_closed_loop_windows.py']
