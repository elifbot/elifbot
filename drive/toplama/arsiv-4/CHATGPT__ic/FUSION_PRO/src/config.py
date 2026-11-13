from pathlib import Path
import yaml

def load_config(path='config.yaml'):
    return yaml.safe_load(Path(path).read_text(encoding='utf-8'))
