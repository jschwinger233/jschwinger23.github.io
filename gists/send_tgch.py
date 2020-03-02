#! /usr/bin/env python3

import os
import sys
import requests
import itertools

try:
    chat_id = sys.argv[2]
except IndexError:
    chat_id = '@TheInfiniteSadness'


def send(buf):
    text = ''.join(buf)
    print(text)
    payload = {
        "chat_id": chat_id,
        "parse_mode": "Markdown",
        "text": text,
    }
    token = os.getenv("TGTOKEN")
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage", json=payload
    )
    print(resp.json())
    resp.raise_for_status()


id = os.path.basename(os.getcwd())
filename = sys.argv[1].split('.')[0]
declaim = f'\nfrom https://gist.github.com/jschwinger23/{id}#file-{filename}-md'

buf = []
length = 0
code_block = False
with open(sys.argv[1]) as f:
    for line in itertools.chain(f, [declaim]):
        if line.startswith('```'):
            code_block = 1 - code_block
            if code_block:
                code_block_buf = []
            else:
                next_chunk = code_block_buf
            code_block_buf.append('```\n')

        elif code_block:
            code_block_buf.append(line)

        elif not code_block:
            next_chunk = [line]

        if length + sum(len(s) for s in next_chunk) > 4096:
            send(buf)
            buf = []
            length = 0

        length += sum(len(s) for s in next_chunk)
        buf.extend(next_chunk)
        next_chunk = []

send(buf)
