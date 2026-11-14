"""Headless smoke test: instantiate the app, cycle it, destroy cleanly."""
import sys
sys.path.insert(0, ".")
import app as appmod

a = appmod.App()
a.url_entry.insert(0, "https://www.youtube.com/playlist?list=test")

def checks():
    ok = True
    # populate a fake playlist to build all row widgets
    vids = [{"id": "jNQXAC9IVRw", "title": "Me at the zoo", "duration": 19,
             "url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"}]
    a._populate(vids, "Test Playlist")
    r = a.rows[0]
    assert r.effective_quality() == "1080p", "quality override failed"
    r.quality_var.set("720p")
    assert r.effective_quality() == "720p", "per-video override failed"
    a.global_quality.set("Audio (MP3)")
    a._on_quality_change()
    a.global_quality.set("1080p")
    a._on_quality_change()
    # command builder sanity
    a.cookies_browser.set("None")
    a.global_bitrate.set("192")
    import subprocess as sp
    a.start_all()
    a.after(300, a.stop_everything)
    a.after(800, a.destroy)

a.after(500, checks)
a.mainloop()
print("SMOKE TEST PASSED")
