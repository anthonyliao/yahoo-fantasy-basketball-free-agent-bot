import base64
import datetime
import json
import logging
import time
from functools import wraps

import requests
import xmltodict

logging.basicConfig(format='%(asctime)s %(levelname)-5s %(message)s', level=logging.INFO)


def with_authorization(func):
    """
    Decorator wrapping a Yahoo API call that automatically renews the authorization token if expired.
    """
    @wraps(func)
    def call(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            if 'token_expired' not in str(e):
                raise e
            with open('api-info.private', 'r') as f:
                api_info = json.load(f)
                client_id = api_info['client_id']
                client_secret = api_info['client_secret']
                logging.info(f'client_id:{client_id}')
                logging.info(f'client_secret:{client_secret}')
            logging.info('renewing token')
            encoded_auth = base64.b64encode(
                f'{client_id}:{client_secret}'.encode('utf-8')).decode('utf-8')
            headers = {
                'Authorization': f'Basic {encoded_auth}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            logging.info(f'headers:{headers}')
            params = {
                'grant_type': 'refresh_token',
                'redirect_url': 'oob',
                'refresh_token': self.refresh
            }
            logging.info(f'params:{params}')
            resp = requests.post(
                'https://api.login.yahoo.com/oauth2/get_token',
                data=params,
                headers=headers
            )
            if resp.status_code != 200:
                raise Exception(f'unable to get new token:{resp.text}')
            resp_json = resp.json()
            with open('token.private', 'w') as f:
                f.write(json.dumps(resp_json, sort_keys=True, indent=4))
            self.access = resp_json['access_token']
            logging.info(f'token renewed:{self.access}')
            return func(self, *args, **kwargs)
    return call


class YahooApi():
    """
    Class containing functions that hit Yahoo's Fantasy API
    (https://developer.yahoo.com/fantasysports/guide/)
    """
    def __init__(self):
        with open('token.private', 'r') as f:
            token = json.load(f)
            self.access = token['access_token']
            self.refresh = token['refresh_token']
            logging.info(f'access:{self.access}')
            logging.info(f'refresh:{self.refresh}')

    @with_authorization
    def make_request(self, is_post, url, data=None):
        headers = {
            'Authorization': f'Bearer {self.access}'
        }
        if is_post:
            headers['Content-Type'] = 'application/xml'

            resp = requests.post(
                url,
                data=data,
                headers=headers
            )
        else:
            requests.get(url, headers=headers)
        logging.info(f'status_code:{resp.status_code}')
        if resp.status_code < 200 or resp.status_code >= 300:
            raise Exception(resp.text)
        return resp

    def player_info(self, league_id, player_id):
        """ Returns ownership details of the player in the league """
        url = f'https://fantasysports.yahooapis.com/fantasy/v2/league/{league_id}/players;player_keys={player_id}/ownership'
        resp = self.make_request(False, url)
        data = xmltodict.parse(resp.text)
        player_obj = data['fantasy_content']['league']['players']['player']
        if isinstance(player_obj, list):
            for player in player_obj:
                yield player['player_key'], player['name']['full'], player
        else:
            yield player_obj['player_key'], player_obj['name']['full'], player_obj

    def add_player(self, league_id, team_id, add_player_id, remove_player_id=None):
        """
        Attempts to add the player to a team & dropping another player if needed.
        """
        url = f'https://fantasysports.yahooapis.com/fantasy/v2/league/{league_id}/transactions'
        data_add = f"""<fantasy_content>
  <transaction>
    <type>add</type>
    <player>
      <player_key>{add_player_id}</player_key>
      <transaction_data>
        <type>add</type>
        <destination_team_key>{team_id}</destination_team_key>
      </transaction_data>
    </player>
  </transaction>
</fantasy_content>"""
        data_replace = f"""<fantasy_content>
  <transaction>
    <type>add/drop</type>
    <players>
      <player>
        <player_key>{add_player_id}</player_key>
        <transaction_data>
          <type>add</type>
          <destination_team_key>{team_id}</destination_team_key>
        </transaction_data>
      </player>
      <player>
        <player_key>{remove_player_id}</player_key>
        <transaction_data>
          <type>drop</type>
          <source_team_key>{team_id}</source_team_key>
        </transaction_data>
      </player>
    </players>
  </transaction>
</fantasy_content>"""
        payload = data_add if remove_player_id is None else data_replace
        logging.debug(f'making request: {payload}')
        resp = self.make_request(True, url, payload)
        logging.debug(f'status_code:{resp.status_code}')
        logging.debug(resp.text)


def add_until_done(caller, league_id, team_id, player_add, player_remove=None):
    while True:
        now = datetime.datetime.now()
        three_am = datetime.datetime(now.year, now.month, now.day, 2, 59, 30)
        seven_am = datetime.datetime(now.year, now.month, now.day, 7, 0, 0)
        secs_until_3 = 0
        if not (three_am < now and now < seven_am):
            if now < three_am:
                secs_until_3 = (three_am - now).seconds
            else:
                secs_until_3 = ((three_am + datetime.timedelta(days=1)) - now).seconds
            logging.info(
                f'waiting {secs_until_3} secs until 3am: approx {now + datetime.timedelta(seconds=secs_until_3)}')
        time.sleep(secs_until_3)

        _, _, player_info = next(caller.player_id(league_id, player_add))
        # waivers, team, freeagents
        ownership = player_info['ownership']['ownership_type']
        if ownership == 'waivers':
            logging.info(f'{player_add} on waivers')
            time.sleep(10)
            continue
        elif ownership == 'team':
            if player_info['ownership']['owner_team_key'] == team_id:
                logging.info(f'{player_add} added')
                return 'owned'
            else:
                logging.info(f'{player_add} taken')
                return 'taken'
        # freeagents
        else:
            try:
                caller.add_player(league_id, team_id, player_add, remove_player_id=player_remove)
            except Exception as e:
                logging.info(f'adding {player_add} failed: {str(e)}')
                time.sleep(1)
                continue


if __name__ == '__main__':
    logging.info('start')

    with open('api-info.private', 'r') as f:
        api_info = json.load(f)
        league_id = api_info['league_id']
        logging.info(f'league_id:{league_id}')
        team_id = api_info['team_id']
        logging.info(f'team_id:{team_id}')
        adds = api_info['player_ids_to_add']
        logging.info(f'player_ids_to_add:{adds}')
        drop = api_info['player_id_to_drop']
        logging.info(f'player_id_to_drop:{drop}')

    caller = YahooApi()

    for player_add in adds:
        status = add_until_done(caller, league_id, team_id, player_add, drop)
        if status == 'owned':
            break

    logging.info('end')
