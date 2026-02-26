# Changelog

## v10.2.2 (2026-02-26)

### Bug fixes


- Handle duplicate camelcase/snake_case keys from protect 7.x ([`c6d5532`](https://github.com/uilibs/uiprotect/commit/c6d553292e0cdbd7cf03f8950ace108fb88252ed))


## v10.2.1 (2026-02-22)

### Bug fixes


- Protect7 missing modelkey ([`0aeb5d3`](https://github.com/uilibs/uiprotect/commit/0aeb5d39185894077f573a9ad27aebbf9d7d83bc))


## v10.2.0 (2026-02-22)

### Features


- Record public api websockets during sample data generation ([`35c30d2`](https://github.com/uilibs/uiprotect/commit/35c30d2f7760ac880bf48a36c44f13b188ae2f62))


## v10.1.0 (2026-01-31)

### Features


- Add retry with exponential backoff ([`14e3617`](https://github.com/uilibs/uiprotect/commit/14e36178d322557858695b9f0e5918c77b27f76d))


## v10.0.1 (2026-01-21)

### Bug fixes


- Update is_package detection logic for g6 entry ([`5ba9026`](https://github.com/uilibs/uiprotect/commit/5ba90263eb64354696014a3095973a0a514058a8))


## v10.0.0 (2026-01-20)

### Features


- Migrate ptz control to public api ([`82ac7f8`](https://github.com/uilibs/uiprotect/commit/82ac7f8610eece008e76b636b1a80a2881eacf8e))


- Migrate ptz control to public api ([`82ac7f8`](https://github.com/uilibs/uiprotect/commit/82ac7f8610eece008e76b636b1a80a2881eacf8e))


- Add ptz preset and patrol retrieval tests ([`82ac7f8`](https://github.com/uilibs/uiprotect/commit/82ac7f8610eece008e76b636b1a80a2881eacf8e))


### Testing


- Add activepatrolslot field to sample data files ([`82ac7f8`](https://github.com/uilibs/uiprotect/commit/82ac7f8610eece008e76b636b1a80a2881eacf8e))


### Bug fixes


- Address pr review comments ([`82ac7f8`](https://github.com/uilibs/uiprotect/commit/82ac7f8610eece008e76b636b1a80a2881eacf8e))


- Restore activepatrolslot in sample_aiport.json for consistency ([`82ac7f8`](https://github.com/uilibs/uiprotect/commit/82ac7f8610eece008e76b636b1a80a2881eacf8e))


## v9.0.0 (2026-01-20)

### Chores


- Drop python 3.10 support ([`0836912`](https://github.com/uilibs/uiprotect/commit/0836912b20ac3677484bbd4d99ae5123803131cb))


## v8.1.1 (2026-01-12)

### Bug fixes


- Re-release ([`dbabddb`](https://github.com/uilibs/uiprotect/commit/dbabddbf61ab68e1fa7ed5e0fd6e7d5a406090a5))


## v8.1.0 (2026-01-12)

### Features


- Add public api support for chime ring volume per camera ([`87782fb`](https://github.com/uilibs/uiprotect/commit/87782fbe688e970cb0e1e1e448683417fb5f57c4))


## v8.0.0 (2026-01-06)

### Features


- Replace ffmpeg with pyav for talkback streaming ([`9998db0`](https://github.com/uilibs/uiprotect/commit/9998db00b0a0f541befe009aee84ad5e92dfb6b9))


## v7.33.4 (2026-01-05)

### Bug fixes


- Update schemas for latest protect version ([`9fa5afa`](https://github.com/uilibs/uiprotect/commit/9fa5afae647ec73206255342dabf2cd08d1285e5))


## v7.33.3 (2025-12-21)

### Bug fixes


- Handle ipv6 addresses in ipv4-typed fields ([`98a39b9`](https://github.com/uilibs/uiprotect/commit/98a39b9aeb94d4d976e9e8b568a214599815365f))


## v7.33.2 (2025-12-05)

### Bug fixes


- Allow dns hostnames with override_connection_host (#679) ([`4f84e69`](https://github.com/uilibs/uiprotect/commit/4f84e69618bfe38e2312dfe558c0649f170928b1))


### Testing


- Add test coverage for _update_bootstrap_soon method ([`cf11161`](https://github.com/uilibs/uiprotect/commit/cf111612fb18409654cda86f8dd4feea80f414b8))


## v7.33.1 (2025-12-01)

### Bug fixes


- Remove deprecated python 3.16 and pydantic v3 patterns ([`b09dab7`](https://github.com/uilibs/uiprotect/commit/b09dab7139e404eaeb8a555da56ae3e0129f1d73))


### Testing


- Add coverage for json deserialization in api_request ([`00eab75`](https://github.com/uilibs/uiprotect/commit/00eab75378fb70f1d9dacc152afb6ec2b06fcaec))


- Improve utils.py test coverage from 45% to 94% ([`2aff97f`](https://github.com/uilibs/uiprotect/commit/2aff97f7fee7cc6816f024b26fab33ea8709b358))


- Add unit tests for _auth_websocket method ([`d1f3841`](https://github.com/uilibs/uiprotect/commit/d1f3841d8838e770d22700bfac273b34fc7f09c4))


## v7.33.0 (2025-11-30)

### Bug fixes


- Make rx_bytes and tx_bytes optional in camerastats ([`8d20059`](https://github.com/uilibs/uiprotect/commit/8d20059c1adc83685c9ccd18e524b1480be7e381))


### Features


- Add ptz public api methods ([`a4e2013`](https://github.com/uilibs/uiprotect/commit/a4e2013124dde43c4aea1975362e01c28013f8f2))


## v7.32.0 (2025-11-29)

### Features


- Add ssl verification prompt with default to disabled ([`f9a07f7`](https://github.com/uilibs/uiprotect/commit/f9a07f707aea417fc7a000fcec6a5fe560964034))


## v7.31.0 (2025-11-29)

### Bug fixes


- Pydantic serialization warnings for camerazone color ([`5869b88`](https://github.com/uilibs/uiprotect/commit/5869b88c549e5f98d31eaf799ae006f30f04bd5d))


### Features


- Add update_light_public() method and fix lux_sensitivity handling ([`ef4e378`](https://github.com/uilibs/uiprotect/commit/ef4e3789fcfdb797ebe0e9b2c437cb4cfb977576))


## v7.30.1 (2025-11-29)

### Bug fixes


- Camera speaker volume ([`ea66817`](https://github.com/uilibs/uiprotect/commit/ea66817c5e05f3acc2da74544f8c431e8e3b28f6))


### Documentation


- Update readme with current features and requirements ([`7301124`](https://github.com/uilibs/uiprotect/commit/73011248abfa7b7febd1a66f4c07a9bd2818d77d))


## v7.30.0 (2025-11-28)

### Features


- Improve devcontainer configuration ([`f32aba2`](https://github.com/uilibs/uiprotect/commit/f32aba29c790a85b8d76686cf86b90dc92b20a94))


## v7.29.0 (2025-11-26)

### Features


- Implement session management with clear_session and clear_all_sessions methods ([`20dbf23`](https://github.com/uilibs/uiprotect/commit/20dbf2336052adf442cf508f5c96bd5a9eff2fb4))


- Enhance rtsp url handling for stacked nvr scenarios ([`80e5370`](https://github.com/uilibs/uiprotect/commit/80e5370e79ea6cd68d0ca0a3b1af9279b0789f63))


## v7.28.0 (2025-11-24)

### Features


- Add support for ufp 6.x detected license plate and face name properties ([`811e2e2`](https://github.com/uilibs/uiprotect/commit/811e2e2b2019a950c8276e21db10f8c209d42d43))


## v7.27.0 (2025-11-24)

### Features


- Update ledsettings for protect 6.x compatibility and add new fields ([`45ab777`](https://github.com/uilibs/uiprotect/commit/45ab77734ac674f4f7ca32441fad118e677ba52d))


## v7.26.0 (2025-11-21)

### Features


- Add ipv6 support for host formatting and connection urls ([`958f139`](https://github.com/uilibs/uiprotect/commit/958f139b0a3becfc8f30cf4509af0aa28cb46696))


## v7.25.0 (2025-11-21)

### Features


- Handle optional doorlocks field in bootstrap class ([`bb589b2`](https://github.com/uilibs/uiprotect/commit/bb589b20132bfbb54c2a053053ff2bf665a7823e))


## v7.24.0 (2025-11-21)

### Features


- Extract and set x-csrf-token during authentication ([`57d878a`](https://github.com/uilibs/uiprotect/commit/57d878a908728ae2d5b5a461d2e749939e8e671d))


## v7.23.0 (2025-10-16)

### Features


- Add events and devices websocket support with subscription handling ([`bf71cb4`](https://github.com/uilibs/uiprotect/commit/bf71cb411e0c90ed008d17e2003f66312ad652d6))


## v7.22.0 (2025-10-14)

### Features


- Remove last uses of pydantic.v1 ([`1d2004b`](https://github.com/uilibs/uiprotect/commit/1d2004bcb5b2c4c78c175c28b1226e797d50ebb8))


## v7.21.1 (2025-08-14)

### Bug fixes


- Remove typer dependency to resolve home assistant version conflicts ([`3619dd2`](https://github.com/uilibs/uiprotect/commit/3619dd2c203eed36ee5c2e77b1b6f20fb35b6380))


## v7.21.0 (2025-08-06)

### Features


- Implement get public api methods for nvr, lights, cameras, and chimes ([`94cc56a`](https://github.com/uilibs/uiprotect/commit/94cc56a9f5bd1feba3a3cf690008966e53d32083))


## v7.20.0 (2025-07-27)

### Features


- Add publicapi rtsps streams management for cameras with create, get, and delete functionalities ([`a53f4b6`](https://github.com/uilibs/uiprotect/commit/a53f4b6e787551aed522e3969914f0a70aa70c96))


## v7.19.0 (2025-07-22)

### Features


- Add methods to set and check api key for nvr ([`166751f`](https://github.com/uilibs/uiprotect/commit/166751fbf403def10763df2294006a96fe49e7db))


## v7.18.1 (2025-07-21)

### Bug fixes


- Ensure highquality parameter is a string in camera pub api snapshot requests ([`57db9e0`](https://github.com/uilibs/uiprotect/commit/57db9e0bdf65b161fcb9d4d7aaf39f8bd8fd4c77))


## v7.18.0 (2025-07-21)

### Features


- Update public api camera snapshot method to accept highquality parameter ([`3df7b70`](https://github.com/uilibs/uiprotect/commit/3df7b7067e8555a405202e49bfe75982c2d9bc71))


## v7.17.0 (2025-07-21)

### Features


- Add support for full hd snapshot feature flag ([`3059e84`](https://github.com/uilibs/uiprotect/commit/3059e84a6d5d6c034b1fb32a897d954aebf661cf))


## v7.16.0 (2025-07-20)

### Features


- Add public api camera snapshot ([`baba0e3`](https://github.com/uilibs/uiprotect/commit/baba0e3ed72dde13fe7113960907b54b87eafcc9))


- Add public api camera snapshot retrieval and related tests ([`baba0e3`](https://github.com/uilibs/uiprotect/commit/baba0e3ed72dde13fe7113960907b54b87eafcc9))


## v7.15.1 (2025-07-20)

### Bug fixes


- Update create_api_key to use 'self' instead of userid ([`755a1b7`](https://github.com/uilibs/uiprotect/commit/755a1b7273d4a97434564f88dbb2502aef61c173))


- Update create_api_key to use 'self' instead of userid and remove related tests ([`755a1b7`](https://github.com/uilibs/uiprotect/commit/755a1b7273d4a97434564f88dbb2502aef61c173))


## v7.15.0 (2025-07-19)

### Features


- Add public api session without cookie and update tests ([`89416ef`](https://github.com/uilibs/uiprotect/commit/89416ef8fe06048677254b95eb0913e6f0106161))


## v7.14.2 (2025-07-08)

### Bug fixes


- Add note about switching to the new public api ([`eb478d2`](https://github.com/uilibs/uiprotect/commit/eb478d2c981fe4c8faa3ad6fa18c47cbc9a7760e))


### Refactoring


- Removes release version retrieval return false for compatibility ([`e646655`](https://github.com/uilibs/uiprotect/commit/e6466558819c414395112fb1858bc5dd28a39c90))


## v7.14.1 (2025-06-21)

### Bug fixes


- Improve uuid handling in convert_unifi_data function ([`6f45e1d`](https://github.com/uilibs/uiprotect/commit/6f45e1d26641a51e43d541c28f3cf9abab355e98))


## v7.14.0 (2025-06-18)

### Features


- Add lpr_reflex to videomode enum ([`bc86bf1`](https://github.com/uilibs/uiprotect/commit/bc86bf15e4437c8ba2d29ed3e4bb7b49c8f09bba))


## v7.13.0 (2025-06-09)

### Features


- Add get_meta_info using public api ([`f30b50a`](https://github.com/uilibs/uiprotect/commit/f30b50a45bb551816bc2284d45d30611ee0d95e4))


## v7.12.0 (2025-06-08)

### Features


- Add optional api key to protectapiclient initialization ([`86e8b54`](https://github.com/uilibs/uiprotect/commit/86e8b54bb662aaf07587452c2a92bf3718756910))


## v7.11.0 (2025-05-31)

### Features


- Add adaptive mode to recordingmode enum ([`4b4155a`](https://github.com/uilibs/uiprotect/commit/4b4155aec2f74076669648194231136774f27198))


- Add adaptive mode to recordingmode enum and update sample_bootstrap.json ([`4b4155a`](https://github.com/uilibs/uiprotect/commit/4b4155aec2f74076669648194231136774f27198))


## v7.10.1 (2025-05-27)

### Bug fixes


- Update codec_to_encoder for correct codec format in talkbackstream ([`dfba227`](https://github.com/uilibs/uiprotect/commit/dfba227a2845c855c275234f5363f42d72eab4f5))


## v7.10.0 (2025-05-25)

### Features


- Add lpr_none_reflex to videomode enum ([`9ab42a0`](https://github.com/uilibs/uiprotect/commit/9ab42a0970c7ba7534996e142dc80a0f20210dc8))


### Unknown



### Bug fixes


- Initialize config dictionary in _read_auth_config method ([`f63e1b3`](https://github.com/uilibs/uiprotect/commit/f63e1b3d8357e82e3f88c07c7c17164140a5aa36))


## v7.9.2 (2025-05-24)

### Bug fixes


- Docker builds ([`f458c4a`](https://github.com/uilibs/uiprotect/commit/f458c4a35aeea78a601ff92719114449412f2a1d))


## v7.9.1 (2025-05-24)

### Bug fixes


- Docker builds ([`8b18b8f`](https://github.com/uilibs/uiprotect/commit/8b18b8fa479c1df833a4a36ad605abdd8cd69bc4))


## v7.9.0 (2025-05-24)

### Features


- Add create api key functionality and corresponding tests ([`3b74740`](https://github.com/uilibs/uiprotect/commit/3b74740cfe256f29970710426165cdb415a15a86))


## v7.8.0 (2025-05-22)

### Features


- Add option to force on flood light for light devices ([`c7c5331`](https://github.com/uilibs/uiprotect/commit/c7c533178722aa49e51fe1d2f8e35f63918f3007))


## v7.7.0 (2025-05-22)

### Features


- Support face detection ([`7f77238`](https://github.com/uilibs/uiprotect/commit/7f772388b7e2a280c2195ec71e6ab936d873abec))


## v7.6.1 (2025-05-22)

### Bug fixes


- Add error handling and logging to get_camera_video() ([`0080f5b`](https://github.com/uilibs/uiprotect/commit/0080f5b5bc6df4661dd4fea0ae2d70ff78099294))


## v7.6.0 (2025-05-07)

### Features


- Add codec mapping for audio encoding in talkbackstream ([`eae52d4`](https://github.com/uilibs/uiprotect/commit/eae52d464eff2a4a4011b760b547ce5ea666e917))


## v7.5.6 (2025-05-02)

### Bug fixes


- Update poetry to v2 ([`ccd89ed`](https://github.com/uilibs/uiprotect/commit/ccd89ed61d19298ba317b2f5a38c449dd3436935))


## v7.5.5 (2025-04-24)

### Bug fixes


- Change phy_rate to float ([`54f60fe`](https://github.com/uilibs/uiprotect/commit/54f60fec70ba5bb75b4efea43a40be70f56e2aeb))


## v7.5.4 (2025-04-12)

### Bug fixes


- Add spdx license identifier ([`85722f6`](https://github.com/uilibs/uiprotect/commit/85722f680d8b727646a165ab13ffa9f8888f5697))


## v7.5.3 (2025-04-11)

### Bug fixes


- Pydantic deprecationwarning ([`0aeb912`](https://github.com/uilibs/uiprotect/commit/0aeb912134fdc203e4fca358b408acada781043c))


## v7.5.2 (2025-03-30)

### Bug fixes


- Support non-integer zoom levels ([`a4976cc`](https://github.com/uilibs/uiprotect/commit/a4976cc50784e246526faa2fe494b51e1f77d8d9))


- Support non-integer zoom levels ([`a4976cc`](https://github.com/uilibs/uiprotect/commit/a4976cc50784e246526faa2fe494b51e1f77d8d9))


## v7.5.1 (2025-02-04)

### Bug fixes


- Handle fps being none ([`c988946`](https://github.com/uilibs/uiprotect/commit/c98894640ca7d70830890a4200cd92df4bf4a029))


- Handle fps being none ([`c988946`](https://github.com/uilibs/uiprotect/commit/c98894640ca7d70830890a4200cd92df4bf4a029))


- Handle fps being none ([`c988946`](https://github.com/uilibs/uiprotect/commit/c98894640ca7d70830890a4200cd92df4bf4a029))


## v7.5.0 (2025-01-24)

### Features


- Update data models to allow none for optional fields to support access devices ([`c6102e4`](https://github.com/uilibs/uiprotect/commit/c6102e4c94899ceebe75d4daddc15981d2368cb3))


- Update data models to allow none for optional fields ([`c6102e4`](https://github.com/uilibs/uiprotect/commit/c6102e4c94899ceebe75d4daddc15981d2368cb3))


- Add new optional fields to recording and camera settings for intercom ([`c6102e4`](https://github.com/uilibs/uiprotect/commit/c6102e4c94899ceebe75d4daddc15981d2368cb3))


## v7.4.1 (2025-01-05)

### Bug fixes


- Handle missing keys in bootstrap data and log an error ([`e06cd7b`](https://github.com/uilibs/uiprotect/commit/e06cd7b2811e2fa292917aec924dfeadc6c43644))


## v7.4.0 (2025-01-04)

### Features


- Add missing ispsettings enum values ([`e593606`](https://github.com/uilibs/uiprotect/commit/e593606debb26c5c7f596037f1739a1881e8d8c8))


## v7.3.0 (2025-01-04)

### Features


- Add none option to autoexposuremode enum ([`04ad788`](https://github.com/uilibs/uiprotect/commit/04ad78889d12a49d2ec415186bc9c8de46903ae9))


## v7.2.0 (2025-01-03)

### Features


- Add set_light_is_led_force_on method ([`5488b1d`](https://github.com/uilibs/uiprotect/commit/5488b1d7accb3d0f3a3df05101b8bc87ef67f25b))


- Add ringtone model and update related functionality ([`d0c93b5`](https://github.com/uilibs/uiprotect/commit/d0c93b5cf562d24acd90dea6e6a77c1ea56b00c1))


- Add ringtone_id and track_no parameters to play chime tones ([`d0c93b5`](https://github.com/uilibs/uiprotect/commit/d0c93b5cf562d24acd90dea6e6a77c1ea56b00c1))


### Unknown



## v7.1.0 (2024-12-18)

### Features


- Add aiport support ([`ba459ff`](https://github.com/uilibs/uiprotect/commit/ba459ff1619957123f71fcf48da7042e3e086ddd))


- Add aiport support ([`ba459ff`](https://github.com/uilibs/uiprotect/commit/ba459ff1619957123f71fcf48da7042e3e086ddd))


## v7.0.2 (2024-12-11)

### Bug fixes


- Migrate more deprecated pydantic calls ([`50ef161`](https://github.com/uilibs/uiprotect/commit/50ef1616429ea013fcb82155beb7510fa0ea156c))


## v7.0.1 (2024-12-11)

### Bug fixes


- Treat no access to keyrings/users as empty ([`c068aca`](https://github.com/uilibs/uiprotect/commit/c068aca46f37f71f52c077b1ab4821bb54d4b26e))


- Treat no access to keyrings/users as empty ([`c068aca`](https://github.com/uilibs/uiprotect/commit/c068aca46f37f71f52c077b1ab4821bb54d4b26e))


- Rushed logic ([`c068aca`](https://github.com/uilibs/uiprotect/commit/c068aca46f37f71f52c077b1ab4821bb54d4b26e))


- Should be a 403 ([`c068aca`](https://github.com/uilibs/uiprotect/commit/c068aca46f37f71f52c077b1ab4821bb54d4b26e))


- Use internal exception ([`c068aca`](https://github.com/uilibs/uiprotect/commit/c068aca46f37f71f52c077b1ab4821bb54d4b26e))


## v7.0.0 (2024-12-11)

### Features


- Remove pydantic v1 shims ([`44063a0`](https://github.com/uilibs/uiprotect/commit/44063a050d831893e7e8eded35ff292401511414))


## v6.8.0 (2024-12-09)

### Bug fixes


- Import of self for python 3.10 ([`fe7fc3a`](https://github.com/uilibs/uiprotect/commit/fe7fc3ad42d1166625b2d0cb3d1f8447b273a1a6))


### Features


- Refactor keyrings and ulpusers to add internal indices ([`705df32`](https://github.com/uilibs/uiprotect/commit/705df32514254b754ebea1ebbc659f669b7ffa10))


- Refactor keyrings and ulpusers ([`705df32`](https://github.com/uilibs/uiprotect/commit/705df32514254b754ebea1ebbc659f669b7ffa10))


## v6.7.0 (2024-12-07)

### Features


- Add keyring and ulp-user ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Add sample data for testing purposes ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Add ulp-user and keyring integration ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Work in progress on adding keyrings functionality ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Add dict_from_unifi_list function and refactor keyrings and ulpusers retrieval ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Define nfc fingerprint support version as constant ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


### Refactoring


- Streamline keyrings and ulpusers handling in protectapiclient ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Replace get_keyrings and get_ulpusers methods with direct dict_from_unifi_list calls ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Update dict_from_unifi_list to use any type for return dictionary ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Rename keyring and ulp_user update methods for clarity and improve message processing ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Improve bootstrap update pop after keyring ulpusr requests ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Remove to_snake_case from update_from_dict ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Typed dict_from_unifi_list ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Update dict_from_unifi_list to use protectmodelwithid type ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Consolidate keyring and ulp user message processing into a single method ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Update device key retrieval and add ulp user management tests ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Improve object removal and update handling in bootstrap class ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Streamline action handling in bootstrap class ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Remove unused user message processing method in bootstrap class ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Move dict_from_unifi_list function to convert module ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


### Bug fixes


- Conditionally assign keyrings and ulp_users based on nvr version ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Convert keys to snake_case in protectbaseobject data processing ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Enhance type checking for model class in bootstrap and update return type in create_from_unifi_dict ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Improve type handling in bootstrap and convert functions for better type safety ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Enhance type safety by casting keyrings and ulp_users in protectapiclient ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Remove type check for protectmodelwithid and enhance mock data in tests ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Add debug logging for unexpected websocket actions and enhance tests for user removal and updates ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Initialize keyrings and ulp_users as empty dictionaries; update return type in dict_from_unifi_list ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


### Testing


- Add websocket tests for keyring add, update, and remove actions ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Add websocket tests for keyring add actions with nfc and fingerprint ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Improve formatting in nfc keyring add test ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Add tests for force update with version checks ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Remove outdated nfc fingerprint support version tests ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


- Remove additional keys from obj_dict in bootstrap test ([`c8a3f4c`](https://github.com/uilibs/uiprotect/commit/c8a3f4c728f888c575d5f3d232149513599e0b5c))


## v6.6.5 (2024-12-02)

### Bug fixes


- Add isthirdpartycamera field to camera model ([`828b510`](https://github.com/uilibs/uiprotect/commit/828b5109f225613f04066eafa1063e6ce715fe3a))


## v6.6.4 (2024-11-29)

### Bug fixes


- Update permission logic for get_snapshot method ([`207959b`](https://github.com/uilibs/uiprotect/commit/207959bf1598acd4ad9e1da1146058b8a18de99c))


- Update permission logic for get_snapshot method ([`207959b`](https://github.com/uilibs/uiprotect/commit/207959bf1598acd4ad9e1da1146058b8a18de99c))


## v6.6.3 (2024-11-27)

### Bug fixes


- Improve partitioned cookie back-compat patching for python 3.13+ ([`a352283`](https://github.com/uilibs/uiprotect/commit/a3522837e283595905907a76671f022b8e680c1d))


## v6.6.2 (2024-11-24)

### Bug fixes


- Bot release token ([`1868448`](https://github.com/uilibs/uiprotect/commit/18684484c76d87d14820f484814097714e71f1a8))


- Update release process to allow the bot to do releases ([`3f7c839`](https://github.com/uilibs/uiprotect/commit/3f7c8393227c9fa78212fa176186027bdb4e9c4d))


- Allow get snapshot with liveonly permissions ([`b2cf95b`](https://github.com/uilibs/uiprotect/commit/b2cf95b45d3815a2c6c5fab962746e8d9d85388d))


### Features


- Allow snapshots with `read_live` permissions ([`b2cf95b`](https://github.com/uilibs/uiprotect/commit/b2cf95b45d3815a2c6c5fab962746e8d9d85388d))


- Enable `read_live` permission for `get_package_snapshot` ([`b2cf95b`](https://github.com/uilibs/uiprotect/commit/b2cf95b45d3815a2c6c5fab962746e8d9d85388d))


### Testing


- Add test data for `read_live` permissions ([`b2cf95b`](https://github.com/uilibs/uiprotect/commit/b2cf95b45d3815a2c6c5fab962746e8d9d85388d))


- Add unit tests for get_snapshot method ([`b2cf95b`](https://github.com/uilibs/uiprotect/commit/b2cf95b45d3815a2c6c5fab962746e8d9d85388d))


## v6.6.1 (2024-11-20)

### Bug fixes


- Handle indexerror selecting value "below 1 lux" for icr_custom_value ([`41f5a3b`](https://github.com/uilibs/uiprotect/commit/41f5a3b4a5fe8999b742a0b245fef6056f5422a7))


## v6.6.0 (2024-11-18)

### Features


- Add feature flags for nfc and fingerprint ([`e208d9e`](https://github.com/uilibs/uiprotect/commit/e208d9e2a73c9a665ef08e8e9341c183f23969aa))


## v6.5.0 (2024-11-17)

### Features


- Add processing for nfc scan and fingerprint identified events ([`0a58b29`](https://github.com/uilibs/uiprotect/commit/0a58b29cef1b4ab67eb25a765c21fc9cb001d1a4))


## v6.4.0 (2024-11-04)

### Features


- Add support for fetching the rtsp url without srtp ([`7d0cfd3`](https://github.com/uilibs/uiprotect/commit/7d0cfd3fe4ae49e485284886b516fbef3ac76a22))


## v6.3.2 (2024-10-29)

### Bug fixes


- Talkback stream bitrate settings ([`f10dedf`](https://github.com/uilibs/uiprotect/commit/f10dedfc5f1108c42310ac15a929b054f57160b8))


## v6.3.1 (2024-10-06)

### Bug fixes


- Typing with version of propcache older than 1.0.0 ([`94f9eaa`](https://github.com/uilibs/uiprotect/commit/94f9eaaa4c17f33f096099d696074ab59377b1ed))


## v6.3.0 (2024-10-06)

### Features


- Add support for propcache v1.0.0+ ([`b37f833`](https://github.com/uilibs/uiprotect/commit/b37f833ed64906a076e13251eb74f8fce605042f))


## v6.2.0 (2024-10-03)

### Features


- Switch to using fast cached_property from propcache ([`e5ce415`](https://github.com/uilibs/uiprotect/commit/e5ce4153cbb42d3f820d40444c2ede8a56133f5a))


## v6.1.0 (2024-09-19)

### Bug fixes


- Add additional types to device_events ([`072bc7c`](https://github.com/uilibs/uiprotect/commit/072bc7cbc6a8af634f4638ac79658715cb31379a))


- Bump psr to 9.8.8 to fix release process ([`b109433`](https://github.com/uilibs/uiprotect/commit/b1094333c8767dd7588fe0d0f97f4c711b7e2595))


### Features


- Speed up url joins ([`a10fc5a`](https://github.com/uilibs/uiprotect/commit/a10fc5adc88a1cf78199f5ca2e4a995032f58743))


## v6.0.2 (2024-08-13)

### Bug fixes


- Bump aiofiles requirement to >=24 ([`1eb9ea7`](https://github.com/uilibs/uiprotect/commit/1eb9ea7c5fb2036ad0af42eb607604652d1b0210))


## v6.0.1 (2024-08-09)

### Bug fixes


- Simplify ssl verify flag in websocket class ([`c36e19a`](https://github.com/uilibs/uiprotect/commit/c36e19a549c78f4fd123b89f562669fdaa5f78a5))


## v6.0.0 (2024-08-08)

### Bug fixes


- Remove default websocket receive timeout ([`8b0b303`](https://github.com/uilibs/uiprotect/commit/8b0b3033880532ddbf00cb59df881100db273dcb))


## v5.4.0 (2024-07-20)

### Features


- Improve performance of convert_unifi_data ([`45f66b4`](https://github.com/uilibs/uiprotect/commit/45f66b4d6f35cbd02abae21f0905089b0e329d59))


## v5.3.0 (2024-07-16)

### Features


- Speed up camera snapshots ([`d333865`](https://github.com/uilibs/uiprotect/commit/d3338658c2fa714e993c3d668945b44a1e7ebd27))


## v5.2.2 (2024-07-04)

### Bug fixes


- Reflection of chime duration seconds ([`0266b8e`](https://github.com/uilibs/uiprotect/commit/0266b8e2470084df63422d4971c04354710b1ae8))


## v5.2.1 (2024-07-04)

### Bug fixes


- Avoid reflecting back smoke_cmonx when changing smart audio ([`7270a5c`](https://github.com/uilibs/uiprotect/commit/7270a5cb40ed9c83db353677abc0496dc7b59f9e))


## v5.2.0 (2024-07-03)

### Features


- Remove deepcopy before calling update_from_dict ([`23bc68f`](https://github.com/uilibs/uiprotect/commit/23bc68f2ca31c06e224cb5f5600ce87e1c842ec6))


## v5.1.0 (2024-07-03)

### Features


- Small cleanups to smart detect lookups ([`ef21763`](https://github.com/uilibs/uiprotect/commit/ef217638129bc48fb67d9e60fe828f78daf2a017))


## v5.0.0 (2024-07-02)

### Features


- Do not auto convert enums to values for fetching attrs ([`f6d7ead`](https://github.com/uilibs/uiprotect/commit/f6d7eade0e2b1dc4073b5e45f7f2a75909180a30))


## v4.2.0 (2024-06-27)

### Features


- Replace manual dict deletes with convertertools ([`22f7df8`](https://github.com/uilibs/uiprotect/commit/22f7df8852d5dcb252337a3f4620932619b6c5be))


## v4.1.0 (2024-06-27)

### Features


- Avoid the need to deepcopy in the ws stats ([`5318b02`](https://github.com/uilibs/uiprotect/commit/5318b0219c89a1183218c94525fe08319208bc30))


## v4.0.0 (2024-06-26)

### Features


- Remove is_ringing property and ring ping back from camera ([`b400435`](https://github.com/uilibs/uiprotect/commit/b400435366c859d0350a9095ae6e9136afb2b08a))


## v3.8.0 (2024-06-26)

### Bug fixes


- Use id checks for type compares ([`0e54ac6`](https://github.com/uilibs/uiprotect/commit/0e54ac6d82e010a6553c7ee7d42d884e8ec0bbd3))


- Use id checks for type compares ([`0e54ac6`](https://github.com/uilibs/uiprotect/commit/0e54ac6d82e010a6553c7ee7d42d884e8ec0bbd3))


- Use id checks for type compares ([`0e54ac6`](https://github.com/uilibs/uiprotect/commit/0e54ac6d82e010a6553c7ee7d42d884e8ec0bbd3))


- Use id checks for type compares ([`0e54ac6`](https://github.com/uilibs/uiprotect/commit/0e54ac6d82e010a6553c7ee7d42d884e8ec0bbd3))


- Use id checks for type compares ([`0e54ac6`](https://github.com/uilibs/uiprotect/commit/0e54ac6d82e010a6553c7ee7d42d884e8ec0bbd3))


- Do not swallow asyncio.cancellederror ([`09bc38b`](https://github.com/uilibs/uiprotect/commit/09bc38b419b26c00363b47c5ae8ce0e6a7280133))


- Remove unreachable code ([`b70d071`](https://github.com/uilibs/uiprotect/commit/b70d071dc52fa179710134e023c34ac0c8caebbe))


- Remove unreachable code ([`b70d071`](https://github.com/uilibs/uiprotect/commit/b70d071dc52fa179710134e023c34ac0c8caebbe))


### Features


- Improve websocket error handling ([`b70d071`](https://github.com/uilibs/uiprotect/commit/b70d071dc52fa179710134e023c34ac0c8caebbe))


- Pass existing data to _handle_ws_error instead of creating it again ([`b70d071`](https://github.com/uilibs/uiprotect/commit/b70d071dc52fa179710134e023c34ac0c8caebbe))


- Cleanup duplicate code in _handle_ws_error ([`b70d071`](https://github.com/uilibs/uiprotect/commit/b70d071dc52fa179710134e023c34ac0c8caebbe))


## v3.7.0 (2024-06-25)

### Features


- Small cleanups to packet packing/unpacking ([`00cb125`](https://github.com/uilibs/uiprotect/commit/00cb125e89f5f43f7c759719d5fc581fb631af3c))


- Small cleanups to devices ([`1b64a8e`](https://github.com/uilibs/uiprotect/commit/1b64a8e89259e9d791a9c9703ced088e4fc7622c))


- Cleanup some additional dupe attr lookups ([`24849d8`](https://github.com/uilibs/uiprotect/commit/24849d819cfbba582a0f21c975de895d3754ef3b))


## v3.6.0 (2024-06-25)

### Features


- Reduce some duplicate attr lookups in devices ([`8ea72ea`](https://github.com/uilibs/uiprotect/commit/8ea72eae1c8c0e37206a1268937287b0b1f29b28))


## v3.5.0 (2024-06-25)

### Features


- Use more list/dict comps where possible ([`9c1ef3f`](https://github.com/uilibs/uiprotect/commit/9c1ef3f30b8e1c01edb5a6d44b0126edd9e3610d))


## v3.4.0 (2024-06-25)

### Features


- Reduce duplicate code to do unifi_dict_to_dict conversions ([`f616c52`](https://github.com/uilibs/uiprotect/commit/f616c528cc94a313dd2ac0ba7e302bfcfca4afde))


## v3.3.1 (2024-06-24)

### Bug fixes


- License classifier ([`ac048d7`](https://github.com/uilibs/uiprotect/commit/ac048d7325529823ab7d2840dc63aaa822008b32))


## v3.3.0 (2024-06-24)

### Features


- Skip empty models in unifi_dict ([`d42023f`](https://github.com/uilibs/uiprotect/commit/d42023f9f07d3bdf097669637e1ad754a70ea0b7))


## v3.2.0 (2024-06-24)

### Features


- Refactor internal object tracking ([`ad1b2b4`](https://github.com/uilibs/uiprotect/commit/ad1b2b45f3d72243ca8cb24c326b4f0fcd0bd71f))


## v3.1.9 (2024-06-24)

### Bug fixes


- Remove event is in range check ([`2847f40`](https://github.com/uilibs/uiprotect/commit/2847f402a19655e9dee1d596b331e70b25bf3da3))


## v3.1.8 (2024-06-23)

### Bug fixes


- Small tweaks to compact code ([`aa136ba`](https://github.com/uilibs/uiprotect/commit/aa136badd8ff7dbad6b74fcd1418de5f8ca04d73))


## v3.1.7 (2024-06-23)

### Bug fixes


- Remove unreachable code in the websocket decoder ([`235cdef`](https://github.com/uilibs/uiprotect/commit/235cdef8bf930fc7b86084fc44cccea96fb316ef))


## v3.1.6 (2024-06-23)

### Bug fixes


- Remove unreachable api in data checks ([`c7772a9`](https://github.com/uilibs/uiprotect/commit/c7772a9ecdf8d29290d0ba84e31a6f104fcb1dd1))


- Make creation of update sync primitives lazy ([`b05af57`](https://github.com/uilibs/uiprotect/commit/b05af578a1ed9b30a1c986a13d006fbaf89b760f))


## v3.1.5 (2024-06-23)

### Bug fixes


- Exclude_fields would mutate the classvar ([`1c461e1`](https://github.com/uilibs/uiprotect/commit/1c461e1a481eb1c022c1dc5aa09529fc1abfec0e))


## v3.1.4 (2024-06-23)

### Bug fixes


- Ensure test harness does not delete coveragerc ([`02bd064`](https://github.com/uilibs/uiprotect/commit/02bd0640fc6ce917db180a410ab0d102b6c8c73a))


## v3.1.3 (2024-06-23)

### Bug fixes


- Add test coverage for updating to none ([`b2adeac`](https://github.com/uilibs/uiprotect/commit/b2adeac94fcef09bac8fe06c9795c8a41694ff95))


## v3.1.2 (2024-06-23)

### Bug fixes


- Coveragerc fails to omit cli and tests ([`d1a4052`](https://github.com/uilibs/uiprotect/commit/d1a4052984e8545b5ac876337909ae235813db7f))


## v3.1.1 (2024-06-22)

### Bug fixes


- _raise_for_status when raise_exception is not set ([`0a6ff9e`](https://github.com/uilibs/uiprotect/commit/0a6ff9e358e66058f2f7ca3bff12925f3b1d4e90))


## v3.1.0 (2024-06-22)

### Features


- Add websocket state subscription ([`d7083ab`](https://github.com/uilibs/uiprotect/commit/d7083ab8ced2dc3cc65dcaf6ea2dd8c869e70a96))


## v3.0.0 (2024-06-22)

### Features


- Remove the force flag from update ([`0bee3e6`](https://github.com/uilibs/uiprotect/commit/0bee3e64d8f1a540e6bfde7b3ab282bc26e6f150))


## v2.3.0 (2024-06-22)

### Features


- Handle websocket auth errors on restart ([`7026491`](https://github.com/uilibs/uiprotect/commit/7026491ac909cb2ed2bf3d9457cf86a1a44de025))


## v2.2.0 (2024-06-22)

### Features


- Decrease websocket logging for known errors ([`05df499`](https://github.com/uilibs/uiprotect/commit/05df499863006b8d66d2ca0e3c76c639730e30de))


## v2.1.0 (2024-06-22)

### Features


- Improve websocket error handling ([`813ac9c`](https://github.com/uilibs/uiprotect/commit/813ac9ca2eaefa2623b15f43d9cdf4f3fab31bcb))


## v2.0.0 (2024-06-22)

### Features


- Rework websocket ([`574a846`](https://github.com/uilibs/uiprotect/commit/574a846ff4e34737169b49ec418b4a112fa12f3e))


## v1.20.0 (2024-06-21)

### Features


- Include getter builder utils for fetching ufp object values ([`9056edf`](https://github.com/uilibs/uiprotect/commit/9056edf85ecf8cd59d053411ae18f1d05093d9e5))


## v1.19.3 (2024-06-21)

### Bug fixes


- Pin and drop pydantic compat imports now that pydantic is fixed ([`00adc2c`](https://github.com/uilibs/uiprotect/commit/00adc2cc39cf004e93952a8ef489ef1051c1fb83))


## v1.19.2 (2024-06-20)

### Bug fixes


- Ensure update_from_dict creates the object is it was previously none ([`f268c01`](https://github.com/uilibs/uiprotect/commit/f268c01bac2b9969f10de70dae2295ce87a6f70b))


## v1.19.1 (2024-06-19)

### Bug fixes


- Update broken documentation readme link ([`1580c04`](https://github.com/uilibs/uiprotect/commit/1580c042d04d989e1ebe4b919df3d232ae4e8ae9))


## v1.19.0 (2024-06-17)

### Features


- Simplify websocket stats logic ([`5b01f34`](https://github.com/uilibs/uiprotect/commit/5b01f34b9c5cc8bcb3cae9f274acd687870a4091))


### Bug fixes


- Refactoring error in 83 ([`ed477c2`](https://github.com/uilibs/uiprotect/commit/ed477c288047fd1fba39f51d6e695adb6a72ba08))


## v1.18.1 (2024-06-17)

### Bug fixes


- Ensure camera and chime keys are not included in the base ignored set ([`02ab5f6`](https://github.com/uilibs/uiprotect/commit/02ab5f696db9497610ec6b34739452abdfe6ca68))


- Ignore cameraids for chime updates ([`3a7e48d`](https://github.com/uilibs/uiprotect/commit/3a7e48dea4111eb6b0a6012ffe08cafcd66cf4d6))


## v1.18.0 (2024-06-17)

### Features


- Add repr for websocket packets ([`60dd356`](https://github.com/uilibs/uiprotect/commit/60dd356a233ab183c31375417ded3f6e53427e5d))


### Refactoring


- Avoid writing out some more key converts ([`851c798`](https://github.com/uilibs/uiprotect/commit/851c7987b772a185fd4c448dddd9e180fd4f16da))


## v1.17.0 (2024-06-17)

### Features


- Improve performance of websocket packet processing ([`58df1c3`](https://github.com/uilibs/uiprotect/commit/58df1c3ac1c050c418d6ea6255ce18ad64422168))


### Refactoring


- Remove and consolidate unused code in base ([`523d931`](https://github.com/uilibs/uiprotect/commit/523d931f6a06b7c66fc7af7cdfac2abf8ebaa737))


- Use tuples for all the delete iterators ([`9ec88ce`](https://github.com/uilibs/uiprotect/commit/9ec88ce68ab5c0d9f6cb30175eb4ffd9b4a47d43))


- Cleanup debug ([`7883c24`](https://github.com/uilibs/uiprotect/commit/7883c24c9b9a08e41ec044e943e6fab3b66a56f1))


- Reduce code to remove keys ([`7b496cb`](https://github.com/uilibs/uiprotect/commit/7b496cb72b3b5efffad18bb86f58355e910122e7))


## v1.16.0 (2024-06-17)

### Features


- Refactor protect obj methods to use comprehensions ([`ae4cdb9`](https://github.com/uilibs/uiprotect/commit/ae4cdb914b162c756f8384c0c25f256fbaa634d7))


## v1.15.0 (2024-06-17)

### Features


- Small cleanup to get device functions ([`86f18d8`](https://github.com/uilibs/uiprotect/commit/86f18d8901d8fd9b6e2ebfa9c3926ed1d1d0e45c))


## v1.14.0 (2024-06-17)

### Features


- Optimize update_from_dict ([`1b8ed6d`](https://github.com/uilibs/uiprotect/commit/1b8ed6dc146c0351927eeb15c47373481b3ad40e))


## v1.13.0 (2024-06-16)

### Features


- Improve performance of processing websocket messages ([`84277cb`](https://github.com/uilibs/uiprotect/commit/84277cb3ac8b47e8d6b483ace8e31c0d9b07baad))


## v1.12.1 (2024-06-16)

### Bug fixes


- Ensure ping back messages are called back and empty updates excluded ([`b319dba`](https://github.com/uilibs/uiprotect/commit/b319dba4b88e0a7d7b237ec57f2e89ca46c1cc6c))


## v1.12.0 (2024-06-16)

### Bug fixes


- Add missing eventstats key to stats_keys ([`6c8be31`](https://github.com/uilibs/uiprotect/commit/6c8be3129c763d6ade16c57df01cc79d57190fef))


### Features


- Small cleanups to bootstrap code ([`78e6dbb`](https://github.com/uilibs/uiprotect/commit/78e6dbb8165b97522b7f42d8f9e885f0e23cd1eb))


## v1.11.1 (2024-06-16)

### Bug fixes


- Revert to using protected attrs for property cache ([`f0b259c`](https://github.com/uilibs/uiprotect/commit/f0b259caaf7c990de68f1a51a0bd166f94eb3bf7))


## v1.11.0 (2024-06-16)

### Features


- Speed up bootstrap by adding cached_property ([`c6b746d`](https://github.com/uilibs/uiprotect/commit/c6b746d8e4d961c0fc1f98d693357e9becd26baa))


## v1.10.0 (2024-06-16)

### Features


- Make websocket dataclasses sloted ([`58e42f6`](https://github.com/uilibs/uiprotect/commit/58e42f69b7603ab77ffe170d091051febe22e48f))


### Performance improvements


- Make websocket dataclass sloted ([`58e42f6`](https://github.com/uilibs/uiprotect/commit/58e42f69b7603ab77ffe170d091051febe22e48f))


## v1.9.0 (2024-06-15)

### Features


- Improve performance of websocket message processing ([`d6a6472`](https://github.com/uilibs/uiprotect/commit/d6a6472d3516e27dcfdd2ed3b5d8ca68428e273f))


## v1.8.0 (2024-06-15)

### Features


- Replace some attrs with cached methods ([`fc0fc57`](https://github.com/uilibs/uiprotect/commit/fc0fc5717a171eb705dce4f88dca79509bd889b4))


- Replace some never used attrs with cached methods ([`fc0fc57`](https://github.com/uilibs/uiprotect/commit/fc0fc5717a171eb705dce4f88dca79509bd889b4))


### Refactoring


- Delete unused bootstrap constants ([`0283c45`](https://github.com/uilibs/uiprotect/commit/0283c4564c905bee1b1f82cc4c0280a02e07ec5d))


- Small cleanups to _process_add_packet ([`8fd8280`](https://github.com/uilibs/uiprotect/commit/8fd82800b63c7cb8c70da164dcc3e1853fc170a6))


## v1.7.2 (2024-06-14)

### Bug fixes


- Pingback did not hold a strong reference to the task ([`7b11ce9`](https://github.com/uilibs/uiprotect/commit/7b11ce952a9e2f66fc5ac9ceccd1a21e74c218b9))


## v1.7.1 (2024-06-14)

### Bug fixes


- Refactoring error in _process_add_packet ([`e21516b`](https://github.com/uilibs/uiprotect/commit/e21516b212762955a49d6da66f2f823a1b252ca2))


## v1.7.0 (2024-06-14)

### Features


- Add debug logging when saving device changes ([`1c57d00`](https://github.com/uilibs/uiprotect/commit/1c57d005f8f97c148b70401256929c262ba5a8a1))


- Add debug logging when saving device changes ([`1c57d00`](https://github.com/uilibs/uiprotect/commit/1c57d005f8f97c148b70401256929c262ba5a8a1))


- Add debug logging when saving device changes ([`1c57d00`](https://github.com/uilibs/uiprotect/commit/1c57d005f8f97c148b70401256929c262ba5a8a1))


### Refactoring


- Cleanup duplicate doorbell text code ([`5e3fac8`](https://github.com/uilibs/uiprotect/commit/5e3fac8b862dfe7df83fe7b5b565578f494b8bf1))


- Cleanup duplicate doorbell text code ([`5e3fac8`](https://github.com/uilibs/uiprotect/commit/5e3fac8b862dfe7df83fe7b5b565578f494b8bf1))


## v1.6.0 (2024-06-14)

### Features


- Simplify object conversions ([`feb8236`](https://github.com/uilibs/uiprotect/commit/feb8236d7e1817a604186a493d57511fff455e47))


## v1.5.0 (2024-06-14)

### Features


- Make audio_type a cached_property ([`50d22de`](https://github.com/uilibs/uiprotect/commit/50d22de5bbf03328c307c7710015e6ec62ab6826))


## v1.4.1 (2024-06-14)

### Bug fixes


- Use none instead of ... for privateattr ([`fc06f42`](https://github.com/uilibs/uiprotect/commit/fc06f420b6c4531dd59bfa3db8b53a965409cac0))


## v1.4.0 (2024-06-14)

### Features


- Only process incoming websocket packet model type once ([`57d7c10`](https://github.com/uilibs/uiprotect/commit/57d7c10d3915fbf45dd81a855298530a36b9e3c7))


## v1.3.0 (2024-06-13)

### Features


- Cleanup duplicate object lookups in event processing ([`ec00121`](https://github.com/uilibs/uiprotect/commit/ec001218a39f7ec10bcc18005e59a1130f16f8aa))


## v1.2.2 (2024-06-13)

### Bug fixes


- Restore some unreachable code in _process_device_update ([`c638cd3`](https://github.com/uilibs/uiprotect/commit/c638cd3b087d63279bd8f798bd8831fc2e11a916))


## v1.2.1 (2024-06-13)

### Bug fixes


- Blocking i/o in the event loop ([`36a4355`](https://github.com/uilibs/uiprotect/commit/36a4355170566b9d7cfb1632d9c35c28b693d9ce))


## v1.2.0 (2024-06-13)

### Features


- Avoid fetching and iterating convert keys when empty ([`7c9ae89`](https://github.com/uilibs/uiprotect/commit/7c9ae89ed667bbe3e9ca2f5561489d4b8335180e))


### Code style


- Remove ide workspace files and add the directories for them to the gitignore ([`486e3f9`](https://github.com/uilibs/uiprotect/commit/486e3f92f4d12ab195f0433e599c9eac0f008aef))


## v1.1.0 (2024-06-12)

### Features


- Remove _get_frame_data helper ([`21d6768`](https://github.com/uilibs/uiprotect/commit/21d6768132d553cc9f59e73cc7adbfde02a42915))


### Refactoring


- Consolidate logic to remove keys ([`9da56d2`](https://github.com/uilibs/uiprotect/commit/9da56d2c0f094d31b0cf8cba07c4c07fd96c64ea))


- Use new _event_is_in_range helper in _process_camera_event ([`49e0a67`](https://github.com/uilibs/uiprotect/commit/49e0a67c5f2473ae1a6bfbe3db513a77786a68df))


- Reduce duplicate code to process sensor events ([`78c291b`](https://github.com/uilibs/uiprotect/commit/78c291b76a0cbce1f891f91c9c01236d71edbf81))


## v1.0.1 (2024-06-11)

### Bug fixes


- New cookie flag preventing auth cookie from being stored ([`b6eb7fc`](https://github.com/uilibs/uiprotect/commit/b6eb7fcef23885d734ba0f9031bf15bdbba91bc5))


## v1.0.0 (2024-06-11)

### Bug fixes


- Remove unused is_ready property from the api client ([`c36ee42`](https://github.com/uilibs/uiprotect/commit/c36ee422ddd04f811019d2e99cbb1d6b398eae01))


### Refactoring


- Use internal self._api inside the object ([`c20e7a9`](https://github.com/uilibs/uiprotect/commit/c20e7a9690a15f42ff0f17105141f21b2e6e4020))


## v0.15.1 (2024-06-11)

### Bug fixes


- Missing url param in websocket disconnected error log message ([`60e6511`](https://github.com/uilibs/uiprotect/commit/60e651110ed935bb0c35b09aedbc2253a73c35a4))


## v0.15.0 (2024-06-11)

### Features


- Cache bootstrap on the protectapiclient once it has been initialized ([`185e47f`](https://github.com/uilibs/uiprotect/commit/185e47fed693c5a6f8383cece10c5267dbb7e046))


## v0.14.0 (2024-06-11)

### Features


- Cache parsing of datetimes ([`8b6747a`](https://github.com/uilibs/uiprotect/commit/8b6747ae41d483da7395f49e402e29f68112fe83))


### Refactoring


- Use f-strings in more places ([`22706c8`](https://github.com/uilibs/uiprotect/commit/22706c896121eac3b6847a951ef516f350119072))


## v0.13.0 (2024-06-11)

### Features


- Cleanup processing camera events ([`2c1a266`](https://github.com/uilibs/uiprotect/commit/2c1a266a3f7c290e4ae9724642eb427ca41cabf1))


## v0.12.0 (2024-06-11)

### Features


- Cleanup websocket add/remove packet processing ([`fdf0f6e`](https://github.com/uilibs/uiprotect/commit/fdf0f6eef96c17c0d2afe008444c24ce8fad72ee))


- Use a single function to normalize mac addresses ([`7ce8654`](https://github.com/uilibs/uiprotect/commit/7ce86543d4ec1efa9143839b1b7be1c6dd977ca1))


## v0.11.0 (2024-06-11)

### Features


- Cleanup processing of websocket packets ([`b59e19c`](https://github.com/uilibs/uiprotect/commit/b59e19c13ea48e5ab235090c1b02d8d73c3aac24))


## v0.10.1 (2024-06-11)

### Bug fixes


- Remove useless time check ([`749cfef`](https://github.com/uilibs/uiprotect/commit/749cfef9b44f87397153977c673c577659450a48))


## v0.10.0 (2024-06-11)

### Features


- Improve performance of process websocket packets ([`7b59c98`](https://github.com/uilibs/uiprotect/commit/7b59c98d02d2f874375b168979a1db253da58914))


## v0.9.0 (2024-06-10)

### Features


- Avoid linear searches to process websocket packets ([`86d5f19`](https://github.com/uilibs/uiprotect/commit/86d5f198071b0478b480804d055ed80c88341ee1))


## v0.8.0 (2024-06-10)

### Features


- Guard debug logging that reformats data in the arguments ([`0cfdea8`](https://github.com/uilibs/uiprotect/commit/0cfdea8d27c0a35d71cd98d65120288218f4ca4c))


### Refactoring


- Remove useless .keys() calls ([`ec1fd12`](https://github.com/uilibs/uiprotect/commit/ec1fd129deb06b5d2334d49ccd0b238033c5b904))


## v0.7.0 (2024-06-10)

### Features


- Refactor protect object subtype bucketing ([`e4123ac`](https://github.com/uilibs/uiprotect/commit/e4123ac13015c186f141c1bfec3a7c064bb2d732))


## v0.6.0 (2024-06-10)

### Features


- Small code cleanups ([`f1668ae`](https://github.com/uilibs/uiprotect/commit/f1668ae2c9c9f49f6e703a387159d305c2cba847))


## v0.5.0 (2024-06-10)

### Features


- Memoize enum type check to speed up data conversion ([`73b0c4a`](https://github.com/uilibs/uiprotect/commit/73b0c4a813e99d3f353a8fbf3d8a997158cedf3a))


## v0.4.1 (2024-06-10)

### Bug fixes


- Handle unifi os 4 token change ([`a6aab8f`](https://github.com/uilibs/uiprotect/commit/a6aab8f1eefd631119288f6d29d643f3984c5b0d))


## v0.4.0 (2024-06-10)

### Features


- Avoid parsing last_update_id ([`ac86b13`](https://github.com/uilibs/uiprotect/commit/ac86b13b3efc8fc619471536ea993f3741882264))


## v0.3.10 (2024-06-10)

### Bug fixes


- Add missing doorbellmessagetype image ([`eaed04b`](https://github.com/uilibs/uiprotect/commit/eaed04bbc1697553895a64edc573d1acc9112a1a))


## v0.3.9 (2024-06-09)

### Bug fixes


- Revert global flags check ([`8dc437f`](https://github.com/uilibs/uiprotect/commit/8dc437f38dc4f6f6081d9a8a80f9f295b31bf579))


## v0.3.8 (2024-06-09)

### Bug fixes


- Improve readme and testdata docs ([`90ae6a8`](https://github.com/uilibs/uiprotect/commit/90ae6a8cec7a10c1631b301a5d64c94bffdee16d))


## v0.3.7 (2024-06-09)

### Bug fixes


- Revert pydantic changes for ha compat ([`c7770c1`](https://github.com/uilibs/uiprotect/commit/c7770c135deaa52da078794c67d5e3f5dbe3455d))


## v0.3.6 (2024-06-09)

### Bug fixes


- Switch readthedocs to mkdocs ([`6009f9d`](https://github.com/uilibs/uiprotect/commit/6009f9dbb5beed141a8af866eb6e1dfd081af067))


- More docs fixes ([`52261ef`](https://github.com/uilibs/uiprotect/commit/52261eff11919768d75e73f9f3a85243c7eff90a))


## v0.3.5 (2024-06-09)

### Bug fixes


- Add missing docs deps ([`399de45`](https://github.com/uilibs/uiprotect/commit/399de45721cb72c1cd6c945ad9aa0d73d82dea8f))


## v0.3.4 (2024-06-09)

### Bug fixes


- Small fixes for readme.md ([`7a0acf4`](https://github.com/uilibs/uiprotect/commit/7a0acf4da9cfcc1cbf6111cc9d2083be68aa9d93))


## v0.3.3 (2024-06-09)

### Bug fixes


- Ensure uv is installed for docker image ([`d286198`](https://github.com/uilibs/uiprotect/commit/d286198ce4d26ff5151c9b937058b4c223aa95f2))


## v0.3.2 (2024-06-09)

### Bug fixes


- Docker file ([`8474862`](https://github.com/uilibs/uiprotect/commit/84748626bbe29492997801759164a6242ebf7b72))


- Update typer ([`54f26b1`](https://github.com/uilibs/uiprotect/commit/54f26b16223d0ed83c2e249df458ec5ccc407fb6))


- Make package installable ([`169e790`](https://github.com/uilibs/uiprotect/commit/169e7903bc72ad513f475c5477c0b6f4cd5c7653))


## v0.3.1 (2024-06-09)

### Bug fixes


- Dockerfile ([`b25d8a1`](https://github.com/uilibs/uiprotect/commit/b25d8a1218158368ec50d1a2b20280b94696ccee))


- Docker ci ([`3d8e9fe`](https://github.com/uilibs/uiprotect/commit/3d8e9fe294c7c75a7efc2d2653a51fdb052fbf29))


## v0.3.0 (2024-06-09)

### Features


- Migrate docs ([`1e62ec2`](https://github.com/uilibs/uiprotect/commit/1e62ec204c6d1b26f95486a8c27a61bb40a8219b))


## v0.2.2 (2024-06-09)

### Bug fixes


- Readme updates ([`8cf5d24`](https://github.com/uilibs/uiprotect/commit/8cf5d24915e9aed2ffbdce4390dd061c9c40d4a1))


## v0.2.1 (2024-06-09)

### Bug fixes


- Adjust jinja check for changelog template ([`e5f55c1`](https://github.com/uilibs/uiprotect/commit/e5f55c1f1af84d3f9053bf9b36c3662dab706882))


- Changelog generation ([`2b770e9`](https://github.com/uilibs/uiprotect/commit/2b770e9a4a6ccfa352fd0fc2b30099ef07b59db8))


## v0.2.0 (2024-06-09)

### Features


- Update classifiers ([`0d4eaf6`](https://github.com/uilibs/uiprotect/commit/0d4eaf6e5fe30c83c52d30d388d65ebe33ee7c3f))


### Unknown



### Bug fixes


- Re-enable changelog ([`68620b0`](https://github.com/uilibs/uiprotect/commit/68620b09b65ee553982c2c54bfc1e0a3c6ba4380))


## v0.1.0 (2024-06-09)

### Bug fixes


- Pre-commit auto update ([`27c1514`](https://github.com/uilibs/uiprotect/commit/27c1514064b5b44d13abd57fc5df3f81dc741c78))


- Cli test ([`b2e4e8e`](https://github.com/uilibs/uiprotect/commit/b2e4e8ef3536bbedc8d3765afb4fd3cb45b478ba))


- Only pyupgrade non-typer code ([`8a5f9b6`](https://github.com/uilibs/uiprotect/commit/8a5f9b644b80a2f739bc5d9720e316150e938ab6))


- Ensure workers ([`d7578de`](https://github.com/uilibs/uiprotect/commit/d7578dedd0443f5ce4333475dde06c28882cbfd0))


- Tests in ci ([`f008537`](https://github.com/uilibs/uiprotect/commit/f0085378ac15125e7e75d80daae7876b37fa8b6d))


- Add mypy to dev deps ([`bde29f2`](https://github.com/uilibs/uiprotect/commit/bde29f236622ec8c3756add4ddb8103644b04c8f))


- More mypy fixes ([`f889c50`](https://github.com/uilibs/uiprotect/commit/f889c5061dd3428bf47bcf1294c0117880e3f20b))


- Add more missing types ([`6d959f9`](https://github.com/uilibs/uiprotect/commit/6d959f9f48b0fd14a43468d52abd8593311bfe10))


- Disable some more rules inline ([`03c726f`](https://github.com/uilibs/uiprotect/commit/03c726f0c0594fcde0a4bb93020c1c99dce6a149))


- Add missing types ([`ef87e72`](https://github.com/uilibs/uiprotect/commit/ef87e72b73e1ec5372bc19260916f093f2b2fe45))


- Disable some rules ([`6cfd103`](https://github.com/uilibs/uiprotect/commit/6cfd103beba3d8689f2c9730831efd89bc0fd679))


### Unknown






## v0.0.0 (2024-06-09)

### Unknown

































































































































































































































































































































































































































































































































































































































































































































































































































### Testing


- Add tests for set_person_track ([`a00de52`](https://github.com/uilibs/uiprotect/commit/a00de52bda63a822f2ffce53bd9188aa7a91def8))


### Documentation


- Add documentation for set_person_track command ([`a00de52`](https://github.com/uilibs/uiprotect/commit/a00de52bda63a822f2ffce53bd9188aa7a91def8))


### Bug fixes


- Actually set chime_duration ([`e7edd26`](https://github.com/uilibs/uiprotect/commit/e7edd26823505f73e97b1a46e70f397a95126a3f))


### Features


- Make chime duration adjustable ([`b4d13c1`](https://github.com/uilibs/uiprotect/commit/b4d13c146f292eae216109f747d3bee6608b0f28))
