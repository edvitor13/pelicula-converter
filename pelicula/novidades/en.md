## Version 1.6.0 — October 29, 2026

**Color and film: log cameras, simple color, a complete lab and real grain.**

- 🎥 **Your camera, done right.** New profiles (Canon Log 2 and 3, F-Log, F-Log2, D-Log, S-Log2, L-Log and LogC3 EI), per-clip camera profiles in Edit mode and automatic suggestions from the file's metadata. Log highlights above white are no longer clipped, and very saturated colors (LED, neon) are protected.
- 🎨 **Simple color.** In Edit mode: white balance eyedropper, automatic from the whole clip, match another clip or an image while protecting skin, click a color and change only it, natural skin, gradient and color groups. Zebra, false color and a reference frame in the preview.
- 🧪 **A complete lab.** Reversal slide, cross processing, expired film, flashing, white-light scanner and films calibrated from Kodak's public data sheets. In Edit mode, **per-clip printer lights** (Alt+R/G/B/D) and, in testing, the **film light meter**, which shows where the negative loses detail or blows out. Four new presets.
- 🌾 **Real grain.** Grain is born in the negative, in each layer, changes with density and can be made of simulated silver grains (Beta). Per-layer softness, breathing and sharpness, and physical halation.
- 📷 **Camera and format.** 180° shutter from 50/60/120 fps video, hand crank, anamorphic lens, date stamp, photo formats (135, half frame, 120), the edit turning into film splices and the **Time machine**: pick a year and where the film was shown.
- 🎛️ **DaVinci Resolve plugin.** It has the new profiles, processes, grain and formats. **Reinstall the plugin** from the app window to get everything.
- 📂 **Projects.** A project that uses something new from 1.6 only opens in 1.6 or newer; older projects open and render the same.

## Version 1.5.0 — October 28, 2026

**Motion, text and subtitles in Edit mode.**

- 🪟 **Transparency.** Videos and images with a transparent background (PNG, ProRes 4444, WebM and the CorridorKey cutout) show over the tracks below instead of on a black background. You can edit on a *Transparent background* and export with transparency to ProRes 4444, WebM or a PNG or TIFF sequence. Numbered image sequences (shot_0001.png…) come in as a single video.
- ◆ **Keyframe animation.** Click the diamond next to a setting to set a key where you are: position, scale, rotation, opacity, color, light, volume and the film settings change over time. The keys show on the timeline, where you can drag them.
- ⏱️ **Clip timing.** A speed ramp with six ready-made shapes (the sound follows without changing pitch), reverse and *Freeze this frame* (Shift+F).
- 🔤 **Titles and generators.** In Media → *New*: solid color, gradient, a countdown leader with a beep, and titles with 11 built-in fonts, six styles and eight animations.
- 🎞️ **Film transitions.** Optical dissolve, fade in and out in exposure, film burn, flash splice, leader and iris, plus push, wipe and zoom. Right-click a clip → *Transition*.
- 💬 **Subtitles.** A panel (Ctrl+Shift+L) and a track on the timeline, tied to the speech even when you cut. YouTube, Reels (word by word) and Cinema styles; import and export .srt and .vtt. When exporting, the subtitles go in the file, burned into the film (with grain and halation), on top of the look or in a file alongside.
- 🎙️ **Subtitles from speech (Beta).** The app transcribes the video on your computer, without sending anything over the internet, and with the timing of each word you can cut by text. It starts turned off: turn it on in Settings → Features by checking *Show features in testing*, and download the transcriber and a model from Components (about 290 MB with the Fast model, or 600 MB with the Accurate one).
- 🔇 **Remove silences.** The app finds the silent parts, shows the list for you to review and removes them all at once (one Ctrl+Z undoes it).
- ✂️ **Cutting tools.** Insert or overwrite when dropping a clip, an optional magnetic main track, Q and W to trim up to the playhead, J and L cuts, and the J, K and L keys to play backward, pause and play forward. **Loop** moved to **Ctrl+L**.
- 🧩 **In your profile.** The new tools follow the profile in Settings → Features: off in Simple; on in Creator, Cinema and Everything.
- 📂 **Projects.** A project that uses something new from 1.5 only opens in 1.5 or newer (1.4 warns you instead of opening it wrong). Older projects open and render the same.
- 🛠️ **Fix.** On Windows, the preview in the export window sometimes showed "Preview unavailable".

## Version 1.4.0 — October 27, 2026

**Exports ready for every platform, markers and chapters, AI keying and an app your way.**

- 📱 **Ready for every platform.** When exporting, pick the platform (YouTube, Shorts, Reels, Stories, TikTok, Kwai, WhatsApp and more, 27 in all) and the app fills in the frame, codec, sound and limits. Crop, add black bars or a blurred background, choose the file size and the loudness. The preview shows the safe area, where the platform's buttons cover the video.
- 📍 **Markers and chapters.** In Edit mode, the M key adds a marker, with a color, name and note. The ones you set as chapters become ready-to-paste text for the YouTube description and go into the MP4, MOV or MKV file.
- ⌨️ **The preview sound has a new key.** It is now **Shift+M**, in both modes. In Film mode, M still works as before.
- 🔊 **Better sound.** An audio meter next to the preview (peaks and loudness in LUFS), smooth audio crossfades between clips and splices without clicks.
- ✂️ **AI keying (Beta).** Remove the green or blue background from a video with CorridorKey, by Corridor Digital. It starts turned off: turn it on in Settings → Features by checking *Show features in testing*. It is a separate download of about 7.6 GB and needs an NVIDIA RTX 30 series card or newer.
- 🧩 **An app your way.** In Settings → Features, keep only the tools you use, one by one or by profile (Simple, Creator, Cinema or Everything). Turning one off only hides it: your projects still render the same. In Components you can see, download, update and remove the extra programs, such as ffmpeg.
- 🔔 **Notifications and recovery.** The app tells you when an export finishes, even with the window minimized. If it closes unexpectedly, the next time it opens it offers to recover the project and the export queue.
- 📷 **Phone HDR.** HDR videos (HLG and PQ, like the iPhone's) are detected and converted automatically.
- 🎨 **S-Log3, V-Log and N-Log with the right exposure.** These profiles read the video on the wrong scale. They are correct now, in the DaVinci plugin too, so older projects that use them may look slightly different (up to about ⅓ stop).
- 🛠️ **Fixes.** Vertical video no longer shrinks in the ready-made qualities; an interrupted export no longer leaves a broken file or deletes the old one; *Tune the encoder for grain* works again; and canceling the close in the update window no longer closes the app.

## Version 1.3.0 — October 19, 2026

**Edit mode, film Lab and a DaVinci Resolve plugin.**

- 🎬 **Edit mode.** At the top of the window, switch between *Film* and *Edit*. In Edit, build the video on picture and sound tracks: import videos, photos and music, cut (S key), trim, move, change the speed and use transitions such as dissolve and fade from black. Then Film mode applies the look on top of the edit.
- 🎨 **Each clip's color and light, made simple.** An *Auto* button, quick looks (Vivid, Warm, Cool, B&W…), exposure, highlights, shadows, color wheels, curve, per-color adjustments (HSL), sharpness and clarity. Copy and paste settings between clips. The scopes show histogram, waveform and vectorscope.
- 🔊 **Each clip's sound.** Volume, fade in and out, bass and treble, voice enhancement and noise reduction.
- 🧪 **Lab.** Simulates the film's path: the negative, the printer lights and the print, including three-strip Technicolor. Color separation (Hue Split), red, green and blue density, bleach bypass and more — with new Kodak and Eastman negatives and prints.
- 📷 **More cameras.** Blackmagic Film Gen 5, ARRI LogC4 and Apple Log (iPhone) inputs.
- 🔌 **DaVinci Resolve plugin.** In Settings → DaVinci Resolve plugin, install the *PeliculaConverter* effect, which works even in the free Resolve, with every preset. For Studio there are also DCTLs and LUTs.
- 📐 **Panels that adapt.** Drag the dividers freely: nothing disappears or gets cut off, and the looks rearrange into columns.

## Version 1.2.2 — October 16, 2026

**Handier full screen and control over the film gauge blur.**

- 🖥️ **Full screen with the player.** In the full-screen preview, the playback controls and the preview bar stay on screen. The resolution you picked is kept, and you can change it right there.
- 🎞️ **Gauge blur.** The slight softness of Super 8 and 8 mm now has its own switch in Film → Gauge blur: turn it off to keep the video sharp, or adjust its strength.

## Version 1.2.1 — October 16, 2026

**Automatic updates work again on Windows.**

- 🔄 **One-click updates, for real.** Before, the app downloaded the new version and closed, but did not install it. Now it installs and reopens by itself, already on the new version.
- ℹ️ **Coming from 1.1.0 or 1.2.0?** Those versions have the bug, so this update must be installed by hand once (download the installer from the website or GitHub). From then on, everything happens on its own.

## Version 1.2.0 — October 16, 2026

**See every detail of the film look.**

- 🖥️ **Full-screen preview.** One click on the full-screen button (or F11) and only the video fills the screen, at the original resolution, so you can check grain, halation and sharpness up close. Esc exits.
- 🔍 **Free zoom.** Use the − and + magnifiers, the + and − keys or the mouse wheel to zoom in or out as much as you like, from 10% to 1600%.
- 📂 **Open projects with the Open button.** .plc files now show up together with videos and images.

## Version 1.1.0 — October 16, 2026

**The app now speaks your language and remembers what you were doing.**

- 🌎 **Portuguese, English and Spanish.** On first launch you pick the language (your computer's language comes preselected). You can change it later in Settings.
- 🎬 **Welcome screen.** When the app opens you see the version, your recent projects and shortcuts to get started: open a video, open a project or use the test scene.
- 💾 **Projects (.plc).** Save your edit and pick up where you left off: the video, the look, every adjustment, the marked range and the frame you were on. Double-click a .plc file to open it straight in the app.
- 🔄 **Automatic updates.** When a new version comes out, the app lets you know and updates itself with one click, checking that the downloaded file is the original.
- 📦 **Installers.** Besides the portable version, there is now an installer for Windows (.msi) and for Linux (.deb), with a menu shortcut and .plc file association.
- ✨ **What's new.** This window! Every time you update, you'll see here what changed, in plain language.

## Version 1.0.0 — October 16, 2026

**The first version of PeliculaConverter.**

- 🎞️ **A movie look for any video.** Negative and theatrical print colors, grain, the reddish glow around lights (halation), bloom and much more — all with an instant preview.
- 📽️ **33 ready-made looks.** Kodak Vision3, Fujifilm Eterna, Super 8 Kodachrome, 16 mm, 65 mm, IMAX, classic black and white, Portra, Velvia, CineStill and more. Tweak any of them and save it as your own.
- 📏 **Film gauges from 8 mm to IMAX.** Each one changes grain size, sharpness, gate weave and the picture's aspect ratio.
- 🎞 **Film scan.** Show the whole film strip, with backlit perforations, edge print and neighboring frames, just like a real scan.
- 🕸️ **Film defects.** Dust, scratches, a hair in the gate, stains, end-of-reel flashes, reel-change cue marks and more — choose which ones appear.
- 📤 **Export to everything.** MP4, MOV, MKV, WebM, AVI, GIF, ProRes and DNxHR masters and a lossless format, with a time estimate and an export queue.
- 🎨 **LUTs.** Use the LUTs you already have and turn any look into a LUT for other programs.
- ⬇️ **Automatic ffmpeg.** If your computer doesn't have ffmpeg (or has a very old one), the app downloads and installs it for you.
