from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent.parent
RAW_FILE_PATH = ROOT / 'raw' / 'steam.jsonl'
LOG_FILE_PATH = ROOT / 'issue' / 'missing_price_id.txt'

def read_by_line_number(file_path, line_number):
    with open(file_path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f, start=1):
            if i == line_number:
                return json.loads(line)
    return None

def write_to_file(file_path, data):
    with open(file_path, 'a', encoding='utf-8') as f:
        f.write(data)
        f.write('\n')

if __name__ == '__main__':
    # data = read_by_line_number(RAW_FILE_PATH, 10)
    with open(RAW_FILE_PATH, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f, start=1):
            data = json.loads(line)
            if data['price_main'] == '':
                write_to_file(LOG_FILE_PATH, data['app_id'])