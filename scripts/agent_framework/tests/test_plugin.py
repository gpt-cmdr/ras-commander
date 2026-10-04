"""Portable plugin filesystem and metadata maintenance contracts (no inference)."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import build_plugin
import refresh_release_snapshot as refresh
import sync_codex_skill_bridge as bridge


class PluginContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / 'repo'
        self.skill = self.repo / '.claude/skills/example'
        self.skill.mkdir(parents=True)
        self.write_skill()
        config = self.repo / '.claude/plugin'
        config.mkdir()
        self.config = config / 'package.json'
        self.config.write_text(json.dumps({'manifest': {'name': 'example', 'version': '0.1.0',
                                              'repository': 'https://github.com/gpt-cmdr/example'},
                                          'skills': ['example']}))
        self.output = Path(self.tmp.name) / 'bundle'

    def write_skill(self, body='', **changes):
        values = {'name': 'example', 'description': 'Example workflow', 'shared_corpus': 'true',
                  'harness_scope': 'shared', 'source_owner': 'gpt-cmdr', 'security_review': 'internal'}
        values.update(changes)
        (self.skill / 'SKILL.md').write_text('---\n' + ''.join(f'{k}: {v}\n' for k, v in values.items()) + '---\n\n' + body)

    def test_transitive_reference_angle_asset_and_provenance(self):
        supporting = self.repo / '.claude/references/shared';supporting.mkdir(parents=True)
        (supporting / 'detail.md').write_text('[asset](<raw data.txt>)\n')
        (supporting / 'raw data.txt').write_bytes(b'source-data')
        self.write_skill('[detail][guide]\n\n[guide]: ../../references/shared/detail.md "Guide"\n')
        build_plugin.build(self.repo, self.output)
        for item in json.loads((self.output / 'source-provenance.json').read_text())['files']:
            source = self.repo / item['source'];packaged = self.output / item['packaged']
            self.assertEqual(item['source_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(item['packaged_sha256'], hashlib.sha256(packaged.read_bytes()).hexdigest())
        self.assertEqual((self.output / 'resources/.claude/references/shared/raw data.txt').read_bytes(), b'source-data')
        self.assertIn('metadata:\n  shared_corpus: "true"', (self.output / 'skills/example/SKILL.md').read_text())

    def test_deterministic_bundles(self):
        build_plugin.build(self.repo, self.output)
        second = self.output.with_name('second')
        build_plugin.build(self.repo, second)
        self.assertEqual({str(p.relative_to(self.output)): p.read_bytes() for p in self.output.rglob('*') if p.is_file()},
                         {str(p.relative_to(second)): p.read_bytes() for p in second.rglob('*') if p.is_file()})

    def test_shared_approval(self):
        for changes in ({'source_owner':'untrusted'}, {'security_review':'unknown'}, {'harness_scope':'claude_only'}, {'shared_corpus':'false'}):
            with self.subTest(changes=changes):
                self.write_skill(**changes)
                with self.assertRaises(ValueError):build_plugin.build(self.repo, self.output)
                self.assertFalse(self.output.exists())

    def test_name_and_description(self):
        for changes in ({'name':'other'}, {'description':''}, {'description':'a'*1025}):
            with self.subTest(changes=changes):
                self.write_skill(**changes)
                with self.assertRaises(ValueError):build_plugin.build(self.repo, self.output)

    def test_traversal_selection(self):
        for name in ('../example', 'example-', 'example--name', '-example', 'Example', 'x'*65):
            with self.subTest(name=name):
                config=json.loads(self.config.read_text());config['skills']=[name];self.config.write_text(json.dumps(config))
                with self.assertRaises(ValueError):build_plugin.build(self.repo,self.output)

    def test_outside_source_link(self):
        outside=self.repo/'outside.md';outside.write_text('private')
        self.write_skill('[escape](../../../outside.md)')
        with self.assertRaises(ValueError):build_plugin.build(self.repo,self.output)
        self.assertFalse(self.output.exists())

    def test_source_symlink_escape(self):
        outside=Path(self.tmp.name)/'private';outside.write_text('private')
        (self.skill/'asset').symlink_to(outside)
        with self.assertRaises(ValueError):build_plugin.build(self.repo,self.output)

    def test_directory_html_and_missing_targets(self):
        for body in ('[missing](missing.md)', '[directory](../)', '<a href="local.md">link</a>'):
            with self.subTest(body=body):
                self.write_skill(body)
                with self.assertRaises((ValueError,FileNotFoundError)):build_plugin.build(self.repo,self.output)

    def test_output_refusal(self):
        self.output.mkdir();(self.output/'retained').write_text('keep')
        with self.assertRaises(ValueError):build_plugin.build(self.repo,self.output)
        self.assertEqual((self.output/'retained').read_text(),'keep')
        with self.assertRaises(ValueError):build_plugin.build(self.repo,self.repo/'.claude/new-output')


class MetadataContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.repo=Path(self.tmp.name);directory=self.repo/'.claude/plugin';directory.mkdir(parents=True)
        (directory/'release-watch.json').write_text(json.dumps({'packages':['example'],'snapshot':'.claude/plugin/release-snapshot.json'}))
        self.snapshot=directory/'release-snapshot.json';self.snapshot.write_text(json.dumps({'packages':{'example':{'status':'not_checked'}}}))
        self.pins=self.repo/'pyproject.toml';self.pins.write_text('dependencies = ["example==1.0"]\n')

    def invoke(self):
        with patch.object(sys,'argv',['refresh','--repo-root',str(self.repo)]):refresh.main()

    def test_changed_unchanged_and_pins(self):
        observation={'status':'released','version':'2.0','qualification':'not_established_by_metadata_check'}
        with patch.object(refresh,'observe',return_value=observation):
            self.invoke();changed=self.snapshot.read_bytes();self.invoke()
            self.assertEqual(changed,self.snapshot.read_bytes())
        self.assertEqual(self.pins.read_text(),'dependencies = ["example==1.0"]\n')
        self.assertEqual(set(self.repo.iterdir()),{self.repo/'.claude',self.pins})

    def test_offline_preserves_snapshot(self):
        previous=self.snapshot.read_bytes()
        with patch.object(refresh,'observe',side_effect=urllib.error.URLError('offline')):
            with self.assertRaises(urllib.error.URLError):self.invoke()
        self.assertEqual(previous,self.snapshot.read_bytes())

    def test_stable_non_yanked_selection(self):
        index={'releases':{'1.0':[{'yanked':False}],'2.0rc1':[{'yanked':False}],'3.0':[{'yanked':True}],'broken':[]}}
        detail={'info':{'requires_python':'>=3.10','requires_dist':['b>=1','a>=1']},'urls':[]}
        with patch.object(refresh,'fetch',side_effect=[index,detail]) as fetch:
            actual=refresh.observe('example')
        self.assertEqual(actual['version'],'1.0');self.assertEqual(actual['requires_dist'],['a>=1','b>=1'])
        self.assertEqual(fetch.call_args.args[0],'https://pypi.org/pypi/example/1.0/json')

    def test_not_published_vs_transient_failure(self):
        with patch.object(refresh,'fetch',side_effect=urllib.error.HTTPError('url',404,'missing',{},None)):
            self.assertEqual(refresh.observe('example')['status'],'not_published')
        with patch.object(refresh,'fetch',side_effect=urllib.error.HTTPError('url',503,'offline',{},None)):
            with self.assertRaises(urllib.error.HTTPError):refresh.observe('example')

    def test_snapshot_escape_refused(self):
        config=self.repo/'.claude/plugin/release-watch.json';config.write_text(json.dumps({'packages':['example'],'snapshot':'escaped.json'}))
        with self.assertRaises(ValueError):self.invoke()
        self.assertFalse((self.repo/'escaped.json').exists())


if __name__=='__main__':unittest.main()
