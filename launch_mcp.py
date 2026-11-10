"""Fixed-root stdio launcher; run with Python -I to ignore ambient module paths."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from pilo_core.mcp_server import serve
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args();serve(args.config)
