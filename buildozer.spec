[app]

title = Trading Helper
package.name = tradinghelper
package.domain = org.test
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 1.0

requirements = python3,kivy,ccxt,requests,pandas,numpy,matplotlib,ta,yfinance,multitasking

android.permissions = INTERNET
android.api = 33
android.minapi = 21
android.archs = arm64-v8a
android.accept_sdk_license = True

icon.filename = icon.png
orientation = portrait

[buildozer]
log_level = 2
warn_on_root = 1
