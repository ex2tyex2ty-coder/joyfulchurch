"""Public role-only entry links. QR codes contain no identity, PIN or room secret."""
from urllib.parse import urlsplit, urlunsplit, urlencode
import streamlit as st


def entry_link(base, role):
    if role not in {'kids','team','desk'}:
        raise ValueError('올바른 사용 화면을 선택해 주세요.')
    parts=urlsplit(base.strip())
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('https://로 시작하는 실제 사이트 주소를 입력해 주세요.')
    return urlunsplit((parts.scheme,parts.netloc,parts.path or '/',urlencode({'sound':role}),''))


def qr_svg(url):
    import qrcode
    from qrcode.image.svg import SvgPathFillImage
    return qrcode.make(url,image_factory=SvgPathFillImage,border=4).to_string(encoding='unicode')


def entry_links_panel():
    with st.expander('키즈룸·찬양팀 입장 QR 만들기'):
        st.caption('배포된 사이트 주소로 만드세요. QR은 화면만 선택하며 음향석 로그인이나 예배방 확인을 건너뛰지 않습니다.')
        base=st.text_input('배포된 사이트 주소',placeholder='https://교회사이트.streamlit.app',key='sound_public_url')
        if not base.strip():
            return
        try:
            for role,label in [('kids','키즈룸'),('team','찬양팀')]:
                url=entry_link(base,role)
                st.write(label+' 전용 입장')
                st.code(url,language=None)
                svg=qr_svg(url)
                st.image(svg,width=200)
                st.download_button(label+' QR 저장',svg,file_name='joyful-'+role+'-qr.svg',mime='image/svg+xml',key='qr_'+role,on_click='ignore')
        except ValueError as exc:
            st.error(str(exc))
        except ImportError:
            st.warning('QR 라이브러리가 아직 설치되지 않았어요. requirements.txt도 업로드하고 Reboot해 주세요. 위 링크는 사용할 수 있습니다.')
