# -*- coding: utf8 -*-
import configparser
import json
import locale
import logging
import random
import re
import sys
import time as tm
from datetime import datetime, timedelta
from enum import Enum
from tempfile import mkdtemp

import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait as Wait
from selenium.common.exceptions import NoSuchElementException
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.firefox import GeckoDriverManager

from utils import Result

console = logging.StreamHandler(sys.stdout)
# file_handler = logging.FileHandler(f'logs/{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')

formatter = logging.Formatter('%(asctime)s - %(levelname)s:%(funcName)s - %(message)s')
console.setFormatter(formatter)
# file_handler.setFormatter(formatter)
logger = logging.getLogger("Visa_Logger")
logger.addHandler(console)
# logger.addHandler(file_handler)
logger.setLevel(logging.DEBUG)

config = configparser.ConfigParser()
config.read('config.ini')

USERNAME = config['USVISA']['USERNAME']
PASSWORD = config['USVISA']['PASSWORD']
SCHEDULE_ID = config['USVISA']['SCHEDULE_ID']
COUNTRY_CODE = config['USVISA']['COUNTRY_CODE']
FACILITY_ID = config['USVISA']['FACILITY_ID']
ASC_ID = config['USVISA']['ASC_ID']
NEED_ASC = config['USVISA'].getboolean('NEED_ASC')

SENDGRID_API_KEY = config['SENDGRID']['SENDGRID_API_KEY']
PUSH_TOKEN = config['PUSHOVER']['PUSH_TOKEN']
PUSH_USER = config['PUSHOVER']['PUSH_USER']

USE = config['CHROMEDRIVER']['USE']
HUB_ADDRESS = config['CHROMEDRIVER']['HUB_ADDRESS']

REGEX_CONTINUE = "//a[contains(text(),'Continue')]"

STEP_TIME = 0.5  # time between steps (interactions with forms): 0.5 seconds

DATE_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/days/{FACILITY_ID}.json?appointments[expedite]=false"
TIME_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/times/{FACILITY_ID}.json?date={{date}}&appointments[expedite]=false"
APPOINTMENT_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment"
DATE_URL_ASC = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/days/{ASC_ID}.json?&consulate_id={FACILITY_ID}&consulate_date={{date}}&consulate_time={{time}}&appointments[expedite]=false"
TIME_URL_ASC = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/times/{ASC_ID}.json?date={{date_asc}}&consulate_id={FACILITY_ID}&consulate_date={{date}}&consulate_time={{time}}&appointments[expedite]=false"

code = COUNTRY_CODE.split("-")
code[1] = code[1].upper()
code = str.join("_", code)
# locale.setlocale(locale.LC_ALL, f'{code}.UTF-8')


class Use(Enum):
    AWS = "AWS"
    LOCAL = "LOCAL"
    REMOTE = "REMOTE"


class VisaScheduler:
    def __init__(self):
        self.driver = self.get_driver()
        self.my_schedule_date = None

    # def MY_CONDITION_DATE(year, month, day): return int(month) == 11 and int(day) >= 5 and int(year) == 2023
    def MY_CONDITION_DATE(self, app_date):
        app_dt = datetime.strptime(app_date, "%Y-%m-%d") 
        return datetime.strptime(self.my_schedule_date, "%Y-%m-%d") - app_dt > timedelta(days=30) and app_dt > datetime.now() + timedelta(days=14)

    # def MY_CONDITION_TIME(hour, minute): return int(hour) >= 8 and int(hour) <= 12 and int(minute) == 0
    @staticmethod
    def MY_CONDITION_TIME(hour, minute):
        return True  # No custom condition wanted for the new scheduled date

    def get_header(self):
        return {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": self.driver.execute_script("return navigator.userAgent;"),
            "Referer": APPOINTMENT_URL,
            "Cookie": "_yatri_session=" + self.driver.get_cookie("_yatri_session")["value"]
        }

    def get_my_schedule_date(self):
        logger.info("Getting my schedule date...")
        element = self.driver.find_element(By.XPATH,
                                           '//a[contains(@href, "%s")]/ancestor::div[contains(@class, "application")]' % SCHEDULE_ID)

        appointment = element.find_element(By.CLASS_NAME, 'consular-appt').text
        regex = r".+: (.+,.+),.+"
        date = re.search(regex, appointment).group(1)
        self.my_schedule_date = datetime.strptime(date, "%d %B, %Y").strftime("%Y-%m-%d")

    def login(self):
        # Bypass reCAPTCHA
        self.driver.get(f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv")
        tm.sleep(STEP_TIME)
        a = self.driver.find_element(By.XPATH, '//a[@class="down-arrow bounce"]')
        a.click()
        tm.sleep(STEP_TIME)

        logger.info("Login start...")
        href = self.driver.find_element(By.XPATH, '//*[@id="main"]/div[2]/div[3]/div[2]/div[1]/div/a')
        href.click()
        tm.sleep(STEP_TIME)
        Wait(self.driver, 60).until(EC.presence_of_element_located((By.NAME, "commit")))

        logger.info("\tclick bounce")
        a = self.driver.find_element(By.XPATH, '//a[@class="down-arrow bounce"]')
        a.click()
        tm.sleep(STEP_TIME)

        self.do_login_action()

    def do_login_action(self):
        logger.info("\tinput email")
        user = self.driver.find_element(By.ID, 'user_email')
        user.send_keys(USERNAME)
        tm.sleep(random.randint(1, 3))

        logger.info("\tinput pwd")
        pw = self.driver.find_element(By.ID, 'user_password')
        pw.send_keys(PASSWORD)
        tm.sleep(random.randint(1, 3))

        logger.info("\tclick privacy")
        box = self.driver.find_element(By.CLASS_NAME, 'icheckbox')
        box.click()
        tm.sleep(random.randint(1, 3))

        logger.info("\tcommit")
        btn = self.driver.find_element(By.NAME, 'commit')
        btn.click()
        tm.sleep(random.randint(1, 3))

        Wait(self.driver, 60).until(
            EC.presence_of_element_located((By.XPATH, REGEX_CONTINUE)))
        logger.info("\tlogin successful!")

    def get_date(self):
        if not self.is_logged_in():
            self.login()
            return self.get_date()
        else:
            logger.info("Getting dates...")
            r = requests.get(DATE_URL, headers=self.get_header())
            date = r.json()
            return date

    def get_time(self, date):
        time_url = TIME_URL.format(date=date)
        r = requests.get(time_url, headers=self.get_header())
        data = r.json()
        times = data.get("available_times")[::-1]
        for t in times:
            hour, minute = t.split(":")
            if self.MY_CONDITION_TIME(hour, minute):
                logger.info(f"Got time successfully! {date} {t}")
                return t

    def reschedule(self, date, time, asc_date=None, asc_time=None):
        logger.info(f"Starting Reschedule ({date})")
        self.send_notification(f"Starting Reschedule ({date})")
        self.driver.get(APPOINTMENT_URL)

        tm.sleep(STEP_TIME)
        try:
            btn = self.driver.find_element(By.XPATH, '//*[@id="main"]/div[3]/form/div[2]/div/input')

            logger.info("\tmultiple applicants")
            btn.click()
        except NoSuchElementException:
            logger.info("\tsingle applicant")

        data = {
            "authenticity_token": self.driver.find_element(by=By.NAME, value='authenticity_token').get_attribute(
                'value'),
            "confirmed_limit_message": self.driver.find_element(by=By.NAME,
                                                                value='confirmed_limit_message').get_attribute(
                'value'),
            "use_consulate_appointment_capacity": self.driver.find_element(by=By.NAME,
                                                                           value='use_consulate_appointment_capacity').get_attribute(
                'value'),
            "appointments[consulate_appointment][facility_id]": FACILITY_ID,
            "appointments[consulate_appointment][date]": date,
            "appointments[consulate_appointment][time]": time,
        }

        if NEED_ASC:
            asc_data = {
                "appointments[asc_appointment][facility_id]": ASC_ID,
                "appointments[asc_appointment][date]": asc_date,
                "appointments[asc_appointment][time]": asc_time
            }
            data.update(asc_data)

        headers = {
            "User-Agent": self.driver.execute_script("return navigator.userAgent;"),
            "Referer": APPOINTMENT_URL,
            "Cookie": "_yatri_session=" + self.driver.get_cookie("_yatri_session")["value"]
        }

        r = requests.post(APPOINTMENT_URL, headers=headers, data=data)
        if r.status_code == 200:
            msg = f"Rescheduled Successfully! {date} {time}" + f", ASC: {asc_date} {asc_time}" if NEED_ASC else ""
            self.send_notification(msg)
            self.driver.quit()
            return Result.SUCCESS
        else:
            msg = f"Reschedule Failed. {date} {time}" + f", ASC: {asc_date} {asc_time}" if NEED_ASC else ""
            self.send_notification(msg)
            logger.error(msg + str(r.status_code) + r.text)
            self.driver.quit()
            return Result.RETRY

    def asc_availability(self, date, time):
        logger.info("ASC Availability")

        def get_date():
            if not self.is_logged_in():
                self.login()
                return get_date()
            else:
                date_url_asc = DATE_URL_ASC.format(date=date, time=time)
                r = requests.get(date_url_asc, headers=self.get_header())
                return r.json()

        def get_available_date(dates):
            for d in dates:
                date = d.get('date')
                # year, month, day = date.split('-')
                if self.MY_CONDITION_DATE(date):
                    return date

        def get_time(date_asc):
            time_url = TIME_URL_ASC.format(date_asc=date_asc, date=date, time=time)
            r = requests.get(time_url, headers=self.get_header())
            data = r.json()
            available_times = data.get("available_times")[::-1]
            for t in available_times:
                hour, minute = t.split(":")
                if self.MY_CONDITION_TIME(hour, minute):
                    logger.info(f"Got time successfully! {date_asc} {t}")
                    return t

        dates = get_date()[:5]
        if not dates:
            return False, (None, None)

        available_date = get_available_date(dates)
        if not available_date:
            return True, (None, None)

        available_time = get_time(available_date)
        if not available_time:
            return True, (available_date, None)

        return True, (available_date, available_time)

    def is_logged_in(self):
        cookie = self.driver.get_cookie("_yatri_session")["value"]
        if len(cookie) <= 350:
            return False
        return True

    @staticmethod
    def get_driver():
        dr = None
        if USE == Use.LOCAL.value:
            #chrome_options = webdriver.ChromeOptions()
            #chrome_options.add_argument('--headless=new')
            # dr = webdriver.Chrome(ChromeDriverManager().install(), options=chrome_options)
            # dr = webdriver.Chrome(executable_path="/home/waqas/visa_rescheduler_aws/chromedriver", options=chrome_options)
            options = webdriver.FirefoxOptions()
            options.add_argument('--headless')
            dr = webdriver.Firefox(executable_path="./geckodriver", options=options)
            
        elif USE == Use.AWS.value:
            chrome_options = webdriver.ChromeOptions()
            chrome_options.binary_location = "/opt/chrome/chrome"
            chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1280x1696')
            chrome_options.add_argument('--single-process')
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-dev-tools")
            chrome_options.add_argument("--no-zygote")
            chrome_options.add_argument('--ignore-certificate-errors')
            chrome_options.add_argument(f'--user-data-dir={mkdtemp()}')
            chrome_options.add_argument(f'--data-path={mkdtemp()}')
            chrome_options.add_argument(f'--disk-cache-dir={mkdtemp()}')
            dr = webdriver.Chrome(service=Service(executable_path="/opt/chromedriver"), options=chrome_options)
        elif USE == Use.REMOTE.value:
            dr = webdriver.Remote(command_executor=HUB_ADDRESS, options=webdriver.ChromeOptions())
        return dr

    def get_available_date(self, dates):

        def is_earlier(date):
            my_date = datetime.strptime(self.my_schedule_date, "%Y-%m-%d")
            new_date = datetime.strptime(date, "%Y-%m-%d")
            result = my_date > new_date
            logger.info(f'Is {my_date} > {new_date}:\t{result}')
            return result

        logger.info("Checking for an earlier date:")
        for d in dates:
            date = d.get('date')
            if is_earlier(date):
                # year, month, day = date.split('-')
                if self.MY_CONDITION_DATE(date):
                    return date
                self.send_notification(f'Available date: {date}, current date: {self.my_schedule_date}, meets conditions?: {self.MY_CONDITION_DATE(date)}')

    @staticmethod
    def send_notification(msg):
        logger.info(f"Sending notification: {msg}")

        if SENDGRID_API_KEY:
            message = Mail(
                from_email=USERNAME,
                to_emails=USERNAME,
                subject=msg,
                html_content=msg)
            try:
                sg = SendGridAPIClient(SENDGRID_API_KEY)
                response = sg.send(message)
                logger.info(f"SendGrid response - {response.status_code} - {response.body} - {response.headers}")
            except Exception as e:
                logger.error(str(e))

        if PUSH_TOKEN:
            url = "https://api.pushover.net/1/messages.json"
            data = {
                "token": PUSH_TOKEN,
                "user": PUSH_USER,
                "message": msg
            }
            requests.post(url, data)

    @staticmethod
    def print_dates(dates):
        logger.info("Available dates:")
        for d in dates:
            logger.info("%s \t business_day: %s" % (d.get('date'), d.get('business_day')))

    def main(self) -> Result:
        # RETRY_TIME
        logger.info(f"---START--- : {datetime.today()}")

        try:
            self.login()
            self.get_my_schedule_date()            
            logger.info(f"Current appointment date: {self.my_schedule_date}")

            dates = self.get_date()[:5]
            if not dates:
                logger.info("No dates available on FACILITY")
                result = Result.COOLDOWN
                self.driver.quit()
                return result

            self.print_dates(dates)
            date = self.get_available_date(dates)

            if not date:
                # No dates that fulfill MY_CONDITION_DATE or early enough
                result = Result.RETRY
                self.driver.quit()
                return result

            date_time = self.get_time(date)

            if not date_time:
                # No times that fulfill MY_CONDITION_TIME
                result = Result.RETRY
                self.driver.quit()
                return result

            logger.info(f"New date: {date} {date_time}")

            if NEED_ASC:
                found, asc_date = self.asc_availability(date, date_time)
                if not found:
                    logger.info("No dates available on ASC")
                    result = Result.COOLDOWN
                    self.driver.quit()
                    return result

                if not asc_date[0] and not asc_date[1]:
                    # No dates that fulfill MY_CONDITION_DATE
                    result = Result.RETRY
                    self.driver.quit()
                    return result

                if not asc_date[1]:
                    # No times that fulfill MY_CONDITION_TIME
                    result = Result.RETRY
                    self.driver.quit()
                    return result

                result = self.reschedule(date, date_time, asc_date[0], asc_date[1])
            else:
                result = self.reschedule(date, date_time)

        except Exception as e:
            self.send_notification("HELP! Crashed.")
            logger.error(e)
            result = Result.EXCEPTION

        self.driver.quit()
        return result
