import sys
import json
import logging
import configparser
from datetime import datetime, timedelta
from visa import VisaScheduler, Result

logger = logging.getLogger("Visa_Logger")

CONFIG_FILE_INI = 'config.ini'
LAST_ACTION_FILE = 'last_action.json'

config_ini = configparser.ConfigParser()
config_ini.read(CONFIG_FILE_INI)
settings = config_ini['SCHEDULING']
retry_time = int(settings.get('RETRY_TIME', 120))
exception_time = int(settings.get('EXCEPTION_TIME', 1800))
cooldown_time = int(settings.get('COOLDOWN_TIME', 3600))

def main():
    with open(LAST_ACTION_FILE, 'r') as file:
        last_action_data = json.load(file)

    last_action = last_action_data.get('last_action', 'RETRY')
    last_action_time = last_action_data.get('last_action_time', None)
    now = datetime.now()

    if last_action not in ('RETRY', 'COOLDOWN', 'EXCEPTION'):
        logger.info("Result is not RETRY, EXCEPTION, or COOLDOWN. Skipping execution.")
        return
    elif last_action == 'COOLDOWN':
        if last_action_time and now < datetime.fromisoformat(last_action_time) + timedelta(seconds=cooldown_time):
            logger.info("Cooldown period is not over. Skipping execution.")
            return
    elif last_action == 'EXCEPTION':
        if last_action_time and now < datetime.fromisoformat(last_action_time) + timedelta(seconds=exception_time):
            logger.info("Exception period is not over. Skipping execution.")
            return

    handler = VisaScheduler()
    result = handler.main()

    last_action_data.update({
        'last_action': result.name,
        'last_action_time': now.isoformat()
    })
    with open(LAST_ACTION_FILE, 'w') as file:
        json.dump(last_action_data, file, indent=4)

    # Optionally print or log the result
    logger.info(f"Result: {result.name}")

if __name__ == "__main__":
    main()
