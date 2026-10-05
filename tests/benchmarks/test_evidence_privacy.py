import hashlib
import json
import tarfile

from benchmarks.spatial import experiments
from scripts.sanitize_evidence import sanitize


def test_snapshot_omits_owner_identity_and_preserves_source_bytes(tmp_path, monkeypatch):
    repository = tmp_path / 'repository'
    repository.mkdir()
    expected = {}
    for name in ('engine', 'api', 'benchmarks', 'scripts'):
        path = repository / name / '__init__.py'
        path.parent.mkdir()
        path.write_bytes(b'VALUE = 1\n')
        expected[path.relative_to(repository).as_posix()] = path.read_bytes()
    config = repository / 'pyproject.toml'
    config.write_bytes(b'[project]\nname = "example"\n')
    expected[config.name] = config.read_bytes()
    output = tmp_path / 'results'
    output.mkdir()
    monkeypatch.setattr(experiments, 'REPOSITORY', repository)
    metadata = experiments.snapshot(output)
    with tarfile.open(output / 'source.tar.gz') as archive:
        actual = {}
        for member in archive:
            assert member.uid == member.gid == 0
            assert member.uname == member.gname == ''
            assert not {'uid', 'gid', 'uname', 'gname'} & member.pax_headers.keys()
            actual[member.name] = archive.extractfile(member).read()
    assert actual == expected
    assert metadata['files'] == {name: hashlib.sha256(data).hexdigest()
                                 for name, data in expected.items()}


def test_sanitize_preserves_json_values_and_removes_local_paths(tmp_path):
    repository = tmp_path / 'project'
    home = '/' + '/'.join(('home', 'local-account', '.cache', 'test.xml'))
    windows = 'C:' + '\\' + '\\'.join(('Users', 'local-account', 'Temp', 'test.xml'))
    mounted = '/' + '/'.join(('mnt', 'c', 'Users', 'local-account', 'Temp', 'test.xml'))
    value = {'result': str(repository / 'output.json'), 'python': home,
             'windows': windows, 'wsl': mounted, 'elapsed_seconds': 1.25,
             'timestamp': '2026-10-04T12:00:00Z', 'rows': 350}
    actual = json.loads(sanitize(json.dumps(value), repository))
    assert actual['result'] == '/workspace/mini-dbms/output.json'
    assert all('local-account' not in actual[key] for key in ('python', 'windows', 'wsl'))
    assert {key: actual[key] for key in ('elapsed_seconds', 'timestamp', 'rows')} == {
        key: value[key] for key in ('elapsed_seconds', 'timestamp', 'rows')}
    assert sanitize(json.dumps(actual), repository) == json.dumps(actual)
