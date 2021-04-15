# yahoo fantasy basketball free agent bot
script that automatically tries to add players if and when they clear waivers at 3AM EST

## prerequisites
* python3+
* pip3

## how to use
```bash
pip3 install -r requirements.txt
# update api-info.private and token.private with yahoo api keys and your league's id
# see https://developer.yahoo.com/apps/create/ and https://developer.yahoo.com/fantasysports/guide/ for more details
# update api-info.private with the player ids to add/drop
python3 freeagent.py
```