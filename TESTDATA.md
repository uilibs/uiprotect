**Dumping Event Log data**

Do the following:

1. Ensure Python 3.8 or 3.9 is installed
2. Install pyunifiprotect by issuing this command: `pip3 install pyunifiprotect`
3. Make sure that you are visible to one of your Cameras, and that motion detection is enabled on that camera
4. Create a `.env` file in your current directory with the following (replacing any values as nessecary):

   ```
   UFP_USERNAME=YOUR_USERNAME_HERE
   UFP_PASSWORD=YOUR_PASSWORD_HERE
   UFP_ADDRESS=YOUR_IP_ADDRESS
   UFP_PORT=443
   UFP_SSL_VERIFY=True
   ```

5. Now run the program you downloaded by issuing this command: `unifi-protect event-data > events.log`
6. While the program is running, make sure you move, so that the Camera detects some motion

There is now a file called `events.log`in your current directory. Please send this to me.
