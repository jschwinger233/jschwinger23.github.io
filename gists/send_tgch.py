#! /usr/bin/env python3

import os
import sys
import requests


def send(buf):
    text = ''.join(buf)
    print(text)
    payload = {
        "chat_id": '@TheInfiniteSadness',
        "parse_mode": "Markdown",
        "text": text,
    }
    token = os.getenv("TGTOKEN")
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json=payload
    )
    print(resp.json())
    resp.raise_for_status()


buf = []
length = 0
code_block = False
with open(sys.argv[1]) as f:
    for line in f:
        if line.startswith('```'):
            code_block = 1 - code_block
            if code_block:
                code_block_buf = []
            else:
                next_chunk = code_block_buf
            code_block_buf.append('```')

        elif code_block:
            next_chunk = []
            code_block_buf.append(line)

        elif not code_block:
            next_chunk = [line]

        if length + sum(len(s) for s in next_chunk) > 4096:
            send(buf)
            buf = []

        else:
            length += sum(len(s) for s in next_chunk)
            buf.extend(next_chunk)

send(buf)

id = os.path.basename(os.getcwd())
filename = os.argv[1].split('.')[0]
send(f'from https://gist.github.com/jschwinger23/{id}#file-{filename}-md')
