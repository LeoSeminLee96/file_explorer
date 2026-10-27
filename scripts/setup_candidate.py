"""Download a verified 0.8B CPU comparison candidate without changing defaults."""
import json
from pathlib import Path
from setup_ai import ROOT, DATA, read_json, download


def main():
    repository = 'ggml-org/Qwen3.5-0.8B-GGUF'
    name = 'Qwen3.5-0.8B-Q4_0.gguf'
    metadata = read_json('https://huggingface.co/api/models/' + repository)
    revision = metadata['sha']
    tree = read_json('https://huggingface.co/api/models/%s/tree/%s' % (repository, revision))
    entry = next(item for item in tree if item['path'] == name)
    checksum = entry['lfs']['oid']
    if entry['size'] > 600 * 1024**2:
        raise ValueError('Candidate exceeds model file budget')
    DATA.mkdir(parents=True, exist_ok=True)
    model = DATA / name
    download('https://huggingface.co/%s/resolve/%s/%s' % (repository, revision, name), model, checksum)
    config = json.loads((ROOT / '.data' / 'model.json').read_text(encoding='utf-8'))
    config.update(model_id='Qwen3.5-0.8B-Q4_0', model_version=revision,
        model_path=str(model.relative_to(ROOT)), parameter_count=800000000, quantization='Q4_0',
        source_sha256=checksum, source_repository='https://huggingface.co/' + repository,
        chat_template='model', temperature=.7)
    target = ROOT / '.data' / 'model-candidate.json'
    target.write_text(json.dumps(config, indent=2), encoding='utf-8')
    print(json.dumps({'candidate_ready': True, 'default_changed': False, 'model_mb': model.stat().st_size / 1024**2}))


if __name__ == '__main__':
    main()
