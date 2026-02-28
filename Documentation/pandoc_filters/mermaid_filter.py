# mermaid_filter.py
from panflute import *

def action(elem, doc):
    if isinstance(elem, CodeBlock) and elem.classes == ['mermaid']:
        return RawBlock(f'<div class="mermaid">\n{elem.text}\n</div>', format='html')

def main(doc=None):
    return run_filter(action, doc=doc)

if __name__ == "__main__":
    main()