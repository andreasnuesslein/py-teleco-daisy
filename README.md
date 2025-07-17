# teleco_daisy


small library to talk to the Teleco Automation Daisy.

this is alpha. currently supported are:

- pergola slats
- pergola rgb light
- pergola white light

if anybody stumbles over this and has different hardware, let me know and we try to integrate it together.



# Development

## HTTP Toolkit and adb

the best way you can get your devices integrated into this project is to:

- download https://httptoolkit.com/
- get yourself an android telephone with ADB (I think it needs to be rooted, not sure right now)
- use HTTP Toolkit and adb mode to selectively sniff the traffic from the Daisy app

if you've come this far, here comes the crucial part:

- when clicking buttons in the daisy app, for let's say turning on your light bulb, you should see a corresponding `teleco/services/tmate20/feedthecommands/` entry in HTTP Toolkit.
- take note of what you did (i.e. "I turned the light on") and the resulting `REQUEST BODY`.
  it will contain something like: 
  ```json
  "commandsList": [
    {
      "commandAction": "POWER",
      "commandId": 100,
      "commandIndex": 0,
      ....
  ``` 

- you will also need to note the **idDevicetype** for the new component that you have. see next section.


## a quick glance at your setup

To help get a quick overview of the items you have and the corresponding `idDevicetype`s, I added a little script to discover your local setup:

`python discover.py <username> <password>`

should produce some output that might already help a tad as well.


