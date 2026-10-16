from pathlib import Path
import sys,os
sys.path.insert(0,r'PROJECT_ROOT\tools')
import macro_runtime as mr
import play_controller_macro as player
mr.MEMSTICK=Path('work/slot1/memstick').resolve()
os.startfile=lambda p:None
sys.argv=['run_sub39',r'PROJECT_ROOT\analysis\sub\sub39_speaker_texture\Naruto_KR_MOV06E_SUB39_SpeakerTexture.iso',r'PROJECT_ROOT\generated_macros\naruto.json']
player.main()
