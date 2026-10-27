"""Install verified CPU-only llama.cpp and quantize official Qwen3 weights locally.

Only this explicit setup command accesses the network. The explorer never downloads
or transmits documents. All destinations are inside the project's .data directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / '.data' / 'ai'
REPO = 'Qwen/Qwen3-0.6B-GGUF'
SOURCE = 'Qwen3-0.6B-Q8_0.gguf'


def request(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'DocumentExplorer-Setup/1.0'}), timeout=60)


def read_json(url):
    with request(url) as response:
        return json.load(response)


def download(url, target, expected=None):
    digest = hashlib.sha256()
    if target.exists():
        with target.open('rb') as stream:
            for block in iter(lambda: stream.read(1024**2), b''):
                digest.update(block)
        if expected and digest.hexdigest() == expected:
            return
    partial = target.with_suffix(target.suffix + '.part')
    digest = hashlib.sha256()
    with request(url) as response, partial.open('wb') as stream:
        size, notice = 0, 0
        while True:
            block = response.read(1024**2)
            if not block:
                break
            stream.write(block)
            digest.update(block)
            size += len(block)
            if size - notice >= 64 * 1024**2:
                print('%s: %.0f MB' % (target.name, size / 1024**2), flush=True)
                notice = size
    if expected and digest.hexdigest() != expected:
        partial.unlink()
        raise ValueError('Download checksum mismatch: ' + target.name)
    partial.replace(target)


def main():
    if os.name != 'nt':
        raise SystemExit('This setup bundles Windows x64 CPU binaries. Set model.json for your platform.')
    DATA.mkdir(parents=True, exist_ok=True)
    # v0.7.0 is a release milestone whose nightly-tag asset pins its binary build.
    with request('https://github.com/ggml-org/llama.cpp/releases/download/v0.7.0/nightly-tag.txt') as response:
        tag = response.read(128).decode().strip()
    if not tag.startswith('b') or not tag[1:].isdigit():
        raise ValueError('Unexpected official runtime tag')
    release = read_json('https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/' + tag)
    asset = next(a for a in release['assets'] if a['name'] == 'llama-%s-bin-win-cpu-x64.zip' % tag)
    checksum = asset.get('digest', '').removeprefix('sha256:')
    if len(checksum) != 64:
        raise ValueError('The official runtime asset has no SHA256 digest')
    runtime_zip = DATA / asset['name']
    print('Runtime: ' + tag, flush=True)
    download(asset['browser_download_url'], runtime_zip, checksum)
    runtime = DATA / 'runtime'
    runtime.mkdir(exist_ok=True)
    with zipfile.ZipFile(runtime_zip) as archive:
        for member in archive.infolist():
            target = (runtime / member.filename).resolve()
            if runtime.resolve() not in target.parents and target != runtime.resolve():
                raise ValueError('Unsafe runtime archive path')
            archive.extract(member, runtime)
    model_meta = read_json('https://huggingface.co/api/models/' + REPO)
    revision = model_meta['sha']
    tree = read_json('https://huggingface.co/api/models/%s/tree/%s' % (REPO, revision))
    source_meta = next(item for item in tree if item['path'] == SOURCE)
    model_hash = source_meta['lfs']['oid']
    source = DATA / SOURCE
    print('Official model: %s @ %s' % (REPO, revision), flush=True)
    download('https://huggingface.co/%s/resolve/%s/%s' % (REPO, revision, SOURCE), source, model_hash)
    quantizer = next(runtime.rglob('llama-quantize.exe'))
    completion = next(runtime.rglob('llama-completion.exe'), None)
    if completion is None:
        completion = next(runtime.rglob('llama-cli.exe'))
    model = DATA / 'Qwen3-0.6B-Q4_K_M.gguf'
    print('Quantizing Q8_0 -> Q4_K_M (CPU only)', flush=True)
    with (DATA / 'quantize.log').open('wb') as log:
        subprocess.run([str(quantizer), '--allow-requantize', str(source), str(model), 'Q4_K_M', '2'], check=True,
                       stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
    if model.stat().st_size > 600 * 1024**2:
        raise ValueError('Quantized model exceeds the small-model budget')
    config = dict(adapter='llama.cpp', model_id='Qwen3-0.6B-Q4_K_M', model_version=revision,
        executable=str(completion.relative_to(ROOT)), model_path=str(model.relative_to(ROOT)),
        server_path=str(next(runtime.rglob('llama-server.exe')).relative_to(ROOT)),
        parameter_count=600000000, quantization='Q4_K_M', context_tokens=2048,
        input_tokens=1400, output_tokens=8, summary_method='ai_source_selection', threads=2, memory_mb=768,
        runtime_version=tag, source_sha256=model_hash, source_repository='https://huggingface.co/' + REPO)
    (ROOT / '.data' / 'model.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    # Keep only the deployed Q4 model, not the larger conversion input or archive.
    source.unlink()
    runtime_zip.unlink()
    print(json.dumps({'ready': True, 'model_mb': model.stat().st_size / 1024**2, 'config': '.data/model.json'}), flush=True)


if __name__ == '__main__':
    main()
