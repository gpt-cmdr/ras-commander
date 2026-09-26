"""Build-time Markdown link conversion; saved code and outputs stay untouched."""
c = get_config()  # noqa: F821 - supplied by traitlets
c.Exporter.preprocessors = ['notebook_docs_preprocessor.DocsMarkdownPreprocessor']
