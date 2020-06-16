**Dumping Event Log data**

Do the following:

1. Ensure Python 3.7 or 3.8 is installed
2. Download [this](https://github.com/briis/pyunifiprotect/blob/master/dumpeventdata.py) file to your computer
3. Edit the file you just downloaded and insert your Unifi Protect Username, Password, IP Address and Port in the relevant places.
4. Install pyunifiprotect by issuing this command: `pip3 install pyunifiprotect`
5. Make sure that you are visible to one of your Cameras, and that motion detection is enabled on that camera
6. Now run the program you downloaded by issuing this command: `python3 dumpeventdata.py > events.log`
7. While the program is running, make sure you move, so that the Camera detects some motion

There is now a file called `events.log`in your current directory. Please send this to me.
