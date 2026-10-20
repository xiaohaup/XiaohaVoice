import os,json
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from concurrent.futures import Future
import pytest
from PySide6.QtCore import QObject,QUrl
from PySide6.QtGui import QPixmap,QImage,QColor
from PySide6.QtWidgets import QApplication
from xiaoha_windows.qt_ui import Palettes,Capsule,NativeChannel
from xiaoha_windows.core import Session

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])

@pytest.fixture
def root(tmp_path):
    catalog=Path(__file__).parents[1]/'devkit/Components/workbench/web/capsule-palettes.json'
    p=tmp_path/'Components/workbench/web';p.mkdir(parents=True);(p/'capsule-palettes.json').write_bytes(catalog.read_bytes())
    (tmp_path/'Data/desktop').mkdir(parents=True);return tmp_path

def test_palette_follow_and_independent_dark(root):
    p=Palettes(root);(root/'Data/capsule-settings.json').write_text('{"mode":"follow"}');(root/'Data/desktop/workbench.json').write_text('{"theme":"mint"}')
    assert p.resolve()['background']=='#f2f4ee'
    p.preview='ink';assert p.resolve()['background']=='#eef2f5'
    (root/'Data/capsule-settings.json').write_text('{"mode":"dark-cocoa"}');assert p.resolve()['background']=='#3d3129'

def test_invalid_palette_falls_back(root):
    (root/'Components/workbench/web/capsule-palettes.json').write_text('{"broken":{"background":"url(evil)"}}')
    (root/'Data/capsule-settings.json').write_text('{"mode":"broken"}')
    assert Palettes(root).resolve()['background']=='#23272f'

def test_native_capsule_renders_without_capture_or_window_presentation(app,root,tmp_path):
    capsule=Capsule(root);session=Session(text='测试实时出字');capsule.update_session(session,'右 Alt')
    capsule.adjustSize();bitmap=QPixmap(capsule.size());capsule.render(bitmap)
    assert bitmap.save(str(tmp_path/'capsule.png')) and not capsule.isVisible() and session.recording
    capsule.close()

@pytest.mark.parametrize('mode',['initial','cocoa','mint','ink','dark-cocoa','dark-mint','dark-ink','follow'])
def test_capsule_panel_is_opaque_with_clear_rounded_corners(app,root,mode):
    (root/'Data/capsule-settings.json').write_text(json.dumps({'mode':mode}))
    (root/'Data/desktop/workbench.json').write_text('{"theme":"mint"}')
    capsule=Capsule(root);capsule.adjustSize()
    image=QImage(capsule.size(),QImage.Format.Format_ARGB32_Premultiplied);image.fill(QColor('transparent'))
    capsule.render(image)
    expected=QColor(capsule.palettes.resolve()['background'])
    for x,y in [(8,capsule.height()//2),(capsule.width()//2,capsule.height()-4)]:
        assert image.pixelColor(x,y).alpha()==255
        assert image.pixelColor(x,y)==expected
    assert image.pixelColor(0,0).alpha()==0
    assert not capsule.isVisible() and not capsule.focusPolicy()
    capsule.close()

class FakePage(QObject):
    def __init__(self,url):super().__init__();self.value=url
    def url(self):return QUrl(self.value)

def test_native_bridge_rejects_external_or_non_main_page(app):
    called=[];page=FakePage('https://example.com/workbench');channel=NativeChannel(page,lambda a,v:called.append(a),'http://127.0.0.1:8766');results=[]
    channel.response.connect(lambda _,raw:results.append(json.loads(raw)))
    channel.postMessage('{"id":"1","action":"copy","value":"text"}')
    assert not called and not results[-1]['ok']
    page.value='http://127.0.0.1:8766/';channel.postMessage('{"id":"2","action":"status"}')
    assert not called and not results[-1]['ok']

def test_native_bridge_handles_async_work_and_errors(app):
    page=FakePage('http://127.0.0.1:8766/workbench#app');future=Future();channel=NativeChannel(page,lambda a,v:future,'http://127.0.0.1:8766');results=[]
    channel.response.connect(lambda _,raw:results.append(json.loads(raw)))
    channel.postMessage('{"id":"1","action":"backupToolkit"}');assert not results
    future.set_result({'records':3});assert results[-1]=={'ok':True,'value':{'records':3}}
