from html.parser import HTMLParser
from pathlib import Path


def test_property_footer_and_results_outside_main():
    class Parser(HTMLParser):
        def __init__(self):super().__init__();self.in_main=False;self.found=set()
        def handle_starttag(self,tag,attrs):
            if tag=='main':self.in_main=True
            if tag=='footer' or dict(attrs).get('id')=='results':
                assert not self.in_main
                self.found.add(tag)
        def handle_endtag(self,tag):
            if tag=='main':self.in_main=False
    parser=Parser();parser.feed((Path(__file__).resolve().parents[1]/'src/edakit/server/web/properties.html').read_text(encoding='utf-8'))
    assert parser.found=={'footer','details'}
