CRATEZ - edits, blends, bootlegs, remixes & packs from SoundCloud, Bandcamp and hearthis.at
===========================================================================================
Downloads into genre folders and straight into Serato DJ crates.

WINDOWS                                      MAC
  1. Unzip somewhere, e.g. C:\Users\you\Cratez   1. Unzip somewhere, e.g. ~/Cratez
  2. Double-click build.bat                      2. Double-click build.command
     (needs Python 3.10+ from python.org)           (needs python3: python.org or "brew install python")
  3. Your app is  dist\Cratez.exe                3. Your app is  dist/Cratez.app  (drag to Applications)
     SmartScreen on first run: More info > Run anyway     First open: right-click > Open (unsigned app)
  Or skip building: double-click run.bat         Or skip building: double-click run.command

  Recommended on both:  ffmpeg
    Windows:  winget install Gyan.FFmpeg        Mac:  brew install ffmpeg
  It gives you title/artist/genre tags, embedded cover art and the MP3-320 conversion option.

SETTINGS (the gear in the sidebar)
  Accounts    SoundCloud: paste your oauth_token cookie (F12 > Application > Cookies > soundcloud.com).
              Bandcamp: paste your identity cookie (same place, bandcamp.com).
              Or import a cookies.txt exported while signed in. Tokens stay on your computer.
  Library     Download folder (Browse...), folder layout (Genre/Uploader, Genre, Uploader or flat),
              whether to append the track id to file names.
  Audio&tags  Stream fallback on/off, metadata tags on/off, cover art on/off, convert streams to
              MP3 320, Bandcamp quality (lossless or MP3 320), how many downloads run at once.
  Serato DJ   Auto-detects your _Serato_ library. Every download is added to a crate
              "Cratez > <Genre>" (subcrates), so they show up in Serato without dragging files in.
              Serato reads crates when it starts: close Serato while Cratez downloads, reopen after.
              Files on an external drive get their crates in that drive's own _Serato_ folder.
              "Add all finished downloads to crates now" rebuilds the crates from your history.
  Searching   Title keywords, default time window, results per search, and skip-if-shorter /
              skip-if-longer limits (drops snippets and full mixes).
  Maintenance Export the "not downloaded" list as CSV (with links, so you can buy / grab them
              elsewhere), open the log folder, clear history, reset settings.

USING IT
  Search      pick a genre, type what you're after (or nothing - genre alone works), choose a time
              window, Search. Download per row or "Download all". Paste a link instead to pull a
              track, a set/album, an artist page or a /likes page.
  My music    load your SoundCloud likes or your Bandcamp purchases and download them into a folder.
  Genres      edit the list (names, SoundCloud tags, search terms). "Collect" runs every search
              term of a genre on all three sites and queues the recent matches; "Collect all
              genres" does the whole list - a weekly run keeps your crate current.
  Downloads   (left column) status and progress; folder button opens the file; click a row for
              details, retry or remove.

WHAT GETS DOWNLOADED
  SoundCloud   the uploader's original file (WAV/MP3 as uploaded) when they've enabled downloads;
               otherwise the stream (160k AAC / 128k MP3) when "Save the stream instead" is on.
  hearthis.at  the uploader's download file when enabled; otherwise the stream (same setting).
  Bandcamp     free / name-your-price-at-zero downloads, and everything you've bought once you sign
               in (albums arrive as a folder). Paid tracks you don't own are listed with a buy link -
               the preview stream is never ripped, that's the artist's shop.

NOTES
  * The sites change often. If searches or downloads start failing, run build.bat / build.command
    again - it pulls the newest yt-dlp.
  * Log file: Windows %APPDATA%\Cratez\cratez.log  -  Mac ~/Library/Application Support/Cratez/cratez.log
  * Stream-saving goes against SoundCloud's terms; keep it for your own library.
