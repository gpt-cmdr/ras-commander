"""Resolve source-notebook Markdown links for the static site, never outputs."""
import re
from urllib.parse import urlsplit, urlunsplit

from nbconvert.preprocessors import Preprocessor


def notebook_links(markdown):
    def replace(match):
        url = urlsplit(match.group(2))
        if url.scheme or url.netloc or not url.path.endswith('.ipynb'):
            return match.group(0)
        target = urlunsplit(('', '', url.path[:-6] + '.md', url.query, url.fragment))
        return match.group(1) + target + match.group(3)
    return re.sub(r'(\]\()([^\s)]+)([^)]*\))', replace, markdown)


class DocsMarkdownPreprocessor(Preprocessor):
    def preprocess_cell(self, cell, resources, index):
        if cell.cell_type == 'markdown':
            cell.source = notebook_links(cell.source)
        return cell, resources
