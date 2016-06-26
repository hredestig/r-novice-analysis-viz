#!/usr/bin/env python

"""
Check lesson files and their contents.
"""

import sys
import os
import glob
import json
import yaml
import re
from optparse import OptionParser

from util import Reporter, read_markdown

__version__ = '0.2'

# Where to look for source Markdown files.
SOURCE_DIRS = ['', '_episodes', '_extras']

# Required files: each entry is ('path': YAML_required).
# FIXME: We do not yet validate whether any files have the required
#   YAML headers, but should in the future.
# The '%' is replaced with the source directory path for checking.
# Episodes are handled specially, and extra files in '_extras' are also handled specially.
# This list must include all the Markdown files listed in the 'bin/initialize' script.
REQUIRED_FILES = {
    '%/CONDUCT.md': True,
    '%/LICENSE.md': True,
    '%/README.md': False,
    '%/_extras/discuss.md': True,
    '%/_extras/figures.md': True,
    '%/_extras/guide.md': True,
    '%/index.md': True,
    '%/reference.md': True,
    '%/setup.md': True,
}

# Episode filename pattern.
P_EPISODE_FILENAME = re.compile(r'/_episodes/(\d\d)-[-\w]+.md$')

# What kinds of blockquotes are allowed?
KNOWN_BLOCKQUOTES = {
    'callout',
    'challenge',
    'checklist',
    'discussion',
    'keypoints',
    'objectives',
    'prereq',
    'quotation',
    'solution',
    'testimonial'
}

# What kinds of code fragments are allowed?
KNOWN_CODEBLOCKS = {
    'error',
    'output',
    'source',
    'bash',
    'make',
    'python',
    'r',
    'sql'
}

# What fields are required in teaching episode metadata?
TEACHING_METADATA_FIELDS = {
    ('title', str),
    ('teaching', int),
    ('exercises', int),
    ('questions', list),
    ('objectives', list),
    ('keypoints', list)
}

# What fields are required in break episode metadata?
BREAK_METADATA_FIELDS = {
    ('layout', str),
    ('title', str),
    ('break', int)
}

# How long are lines allowed to be?
MAX_LINE_LEN = 100

def main():
    """Main driver."""

    args = parse_args()
    args.reporter = Reporter()
    check_config(args.reporter, args.source_dir)
    docs = read_all_markdown(args.source_dir, args.parser)
    check_fileset(args.source_dir, args.reporter, docs.keys())
    for filename in docs.keys():
        checker = create_checker(args, filename, docs[filename])
        checker.check()
    args.reporter.report()


def parse_args():
    """Parse command-line arguments."""

    parser = OptionParser()
    parser.add_option('-l', '--linelen',
                      default=False,
                      dest='line_len',
                      help='Check line lengths')
    parser.add_option('-p', '--parser',
                      default=None,
                      dest='parser',
                      help='path to Markdown parser')
    parser.add_option('-s', '--source',
                      default=os.curdir,
                      dest='source_dir',
                      help='source directory')

    args, extras = parser.parse_args()
    require(args.parser is not None,
            'Path to Markdown parser not provided')
    require(not extras,
            'Unexpected trailing command-line arguments "{0}"'.format(extras))

    return args


def check_config(reporter, source_dir):
    """Check configuration file."""

    config_file = os.path.join(source_dir, '_config.yml')
    with open(config_file, 'r') as reader:
        config = yaml.load(reader)
    reporter.check_field(config_file, 'configuration', config, 'kind', 'lesson')


def read_all_markdown(source_dir, parser):
    """Read source files, returning
    {path : {'metadata':yaml, 'metadata_len':N, 'text':text, 'lines':[(i, line, len)], 'doc':doc}}
    """

    all_dirs = [os.path.join(source_dir, d) for d in SOURCE_DIRS]
    all_patterns = [os.path.join(d, '*.md') for d in all_dirs]
    result = {}
    for pat in all_patterns:
        for filename in glob.glob(pat):
            data = read_markdown(parser, filename)
            if data:
                result[filename] = data
    return result


def check_fileset(source_dir, reporter, filenames_present):
    """Are all required files present? Are extraneous files present?"""

    # Check files with predictable names.
    required = [p.replace('%', source_dir) for p in REQUIRED_FILES]
    missing = set(required) - set(filenames_present)
    for m in missing:
        reporter.add(None, 'Missing required file {0}', m)

    # Check episode files' names.
    seen = []
    for filename in filenames_present:
        if '_episodes' not in filename:
            continue
        m = P_EPISODE_FILENAME.search(filename)
        if m and m.group(1):
            seen.append(m.group(1))
        else:
            reporter.add(None, 'Episode {0} has badly-formatted filename', filename)

    # Check for duplicate episode numbers.
    reporter.check(len(seen) == len(set(seen)),
                        None,
                        'Duplicate episode numbers {0} vs {1}',
                        sorted(seen), sorted(set(seen)))

    # Check that numbers are consecutive.
    seen = [int(s) for s in seen]
    seen.sort()
    clean = True
    for i in range(len(seen) - 1):
        clean = clean and ((seen[i+1] - seen[i]) == 1)
    reporter.check(clean,
                   None,
                   'Missing or non-consecutive episode numbers {0}',
                   seen)


def create_checker(args, filename, info):
    """Create appropriate checker for file."""

    for (pat, cls) in CHECKERS:
        if pat.search(filename):
            return cls(args, filename, **info)


def require(condition, message):
    """Fail if condition not met."""

    if not condition:
        print(message, file=sys.stderr)
        sys.exit(1)


class CheckBase(object):
    """Base class for checking Markdown files."""

    def __init__(self, args, filename, metadata, metadata_len, text, lines, doc):
        """Cache arguments for checking."""

        super(CheckBase, self).__init__()
        self.args = args
        self.reporter = self.args.reporter # for convenience
        self.filename = filename
        self.metadata = metadata
        self.metadata_len = metadata_len
        self.text = text
        self.lines = lines
        self.doc = doc

        self.layout = None


    def check(self):
        """Run tests on metadata."""

        self.check_metadata()
        self.check_text()
        self.check_blockquote_classes()
        self.check_codeblock_classes()


    def check_metadata(self):
        """Check the YAML metadata."""

        self.reporter.check(self.metadata is not None,
                            self.filename,
                            'Missing metadata entirely')

        if self.metadata and (self.layout is not None):
            self.reporter.check_field(self.filename, 'metadata', self.metadata, 'layout', self.layout)


    def check_text(self):
        """Check the raw text of the lesson body."""

        if self.args.line_len:
            over = [i for (i, l, n) in self.lines if (n > MAX_LINE_LEN) and (not l.startswith('!'))]
            self.reporter.check(not over,
                                self.filename,
                                'Line(s) are too long: {0}',
                                ', '.join([str(i) for i in over]))


    def check_blockquote_classes(self):
        """Check that all blockquotes have known classes."""

        for node in self.find_all(self.doc, {'type' : 'blockquote'}):
            cls = self.get_val(node, 'attr', 'class')
            self.reporter.check(cls in KNOWN_BLOCKQUOTES,
                                (self.filename, self.get_loc(node)),
                                'Unknown or missing blockquote type {0}',
                                cls)


    def check_codeblock_classes(self):
        """Check that all code blocks have known classes."""

        for node in self.find_all(self.doc, {'type' : 'codeblock'}):
            cls = self.get_val(node, 'attr', 'class')
            self.reporter.check(cls in KNOWN_CODEBLOCKS,
                                (self.filename, self.get_loc(node)),
                                'Unknown or missing code block type {0}',
                                cls)


    def find_all(self, node, pattern, accum=None):
        """Find all matches for a pattern."""

        assert type(pattern) == dict, 'Patterns must be dictionaries'
        if accum is None:
            accum = []
        if self.match(node, pattern):
            accum.append(node)
        for child in node.get('children', []):
            self.find_all(child, pattern, accum)
        return accum


    def match(self, node, pattern):
        """Does this node match the given pattern?"""

        for key in pattern:
            if key not in node:
                return False
            val = pattern[key]
            if type(val) == str:
                if node[key] != val:
                    return False
            elif type(val) == dict:
                if not self.match(node[key], val):
                    return False
        return True


    def get_val(self, node, *chain):
        """Get value one or more levels down."""

        curr = node
        for selector in chain:
            curr = curr.get(selector, None)
            if curr is None:
                break
        return curr


    def get_loc(self, node):
        """Convenience method to get node's line number."""

        result = self.get_val(node, 'options', 'location')
        if self.metadata_len is not None:
            result += self.metadata_len
        return result


class CheckNonJekyll(CheckBase):
    """Check a file that isn't translated by Jekyll."""

    def __init__(self, args, filename, metadata, metadata_len, text, lines, doc):
        super(CheckNonJekyll, self).__init__(args, filename, metadata, metadata_len, text, lines, doc)


    def check_metadata(self):
        self.reporter.check(self.metadata is None,
                            self.filename,
                            'Unexpected metadata')


class CheckIndex(CheckBase):
    """Check the main index page."""

    def __init__(self, args, filename, metadata, metadata_len, text, lines, doc):
        super(CheckIndex, self).__init__(args, filename, metadata, metadata_len, text, lines, doc)
        self.layout = 'lesson'


class CheckEpisode(CheckBase):
    """Check an episode page."""

    def __init__(self, args, filename, metadata, metadata_len, text, lines, doc):
        super(CheckEpisode, self).__init__(args, filename, metadata, metadata_len, text, lines, doc)

    def check_metadata(self):
        super(CheckEpisode, self).check_metadata()
        if self.metadata:
            if 'layout' in self.metadata:
                if self.metadata['layout'] == 'break':
                    self.check_metadata_fields(BREAK_METADATA_FIELDS)
                else:
                    self.reporter.add(self.filename,
                                      'Unknown episode layout "{0}"',
                                      self.metadata['layout'])
            else:
                self.check_metadata_fields(TEACHING_METADATA_FIELDS)


    def check_metadata_fields(self, expected):
        for (name, type_) in expected:
            if name not in self.metadata:
                self.reporter.add(self.filename,
                                  'Missing metadata field {0}',
                                  name)
            elif type(self.metadata[name]) != type_:
                self.reporter.add(self.filename,
                                  '"{0}" has wrong type in metadata ({1} instead of {2})',
                                  name, type(self.metadata[name]), type_)


class CheckReference(CheckBase):
    """Check the reference page."""

    def __init__(self, args, filename, metadata, metadata_len, text, lines, doc):
        super(CheckReference, self).__init__(args, filename, metadata, metadata_len, text, lines, doc)
        self.layout = 'reference'


class CheckGeneric(CheckBase):
    """Check a generic page."""

    def __init__(self, args, filename, metadata, metadata_len, text, lines, doc):
        super(CheckGeneric, self).__init__(args, filename, metadata, metadata_len, text, lines, doc)
        self.layout = 'page'


CHECKERS = [
    (re.compile(r'CONTRIBUTING\.md'), CheckNonJekyll),
    (re.compile(r'README\.md'), CheckNonJekyll),
    (re.compile(r'index\.md'), CheckIndex),
    (re.compile(r'reference\.md'), CheckReference),
    (re.compile(r'_episodes/.*\.md'), CheckEpisode),
    (re.compile(r'.*\.md'), CheckGeneric)
]


if __name__ == '__main__':
    main()
