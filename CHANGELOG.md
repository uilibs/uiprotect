# Changelog

## v3.1.3 (2024-06-23)

### Fix


- Add test coverage for updating to none (#107) ([`b2adeac`](https://github.com/uilibs/uiprotect/commit/b2adeac94fcef09bac8fe06c9795c8a41694ff95))


## v3.1.2 (2024-06-23)

### Fix


- Coveragerc fails to omit cli and tests (#106) ([`d1a4052`](https://github.com/uilibs/uiprotect/commit/d1a4052984e8545b5ac876337909ae235813db7f))


## v3.1.1 (2024-06-22)

### Fix


- _raise_for_status when raise_exception is not set (#105) ([`0a6ff9e`](https://github.com/uilibs/uiprotect/commit/0a6ff9e358e66058f2f7ca3bff12925f3b1d4e90))


## v3.1.0 (2024-06-22)

### Feature


- Add websocket state subscription (#104) ([`d7083ab`](https://github.com/uilibs/uiprotect/commit/d7083ab8ced2dc3cc65dcaf6ea2dd8c869e70a96))


## v3.0.0 (2024-06-22)

### Breaking


- Remove the force flag from update (#103) ([`0bee3e6`](https://github.com/uilibs/uiprotect/commit/0bee3e64d8f1a540e6bfde7b3ab282bc26e6f150))


## v2.3.0 (2024-06-22)

### Feature


- Handle websocket auth errors on restart (#102) ([`7026491`](https://github.com/uilibs/uiprotect/commit/7026491ac909cb2ed2bf3d9457cf86a1a44de025))


## v2.2.0 (2024-06-22)

### Feature


- Decrease websocket logging for known errors (#101) ([`05df499`](https://github.com/uilibs/uiprotect/commit/05df499863006b8d66d2ca0e3c76c639730e30de))


## v2.1.0 (2024-06-22)

### Feature


- Improve websocket error handling (#100) ([`813ac9c`](https://github.com/uilibs/uiprotect/commit/813ac9ca2eaefa2623b15f43d9cdf4f3fab31bcb))


## v2.0.0 (2024-06-22)

### Breaking


- Rework websocket (#96) ([`574a846`](https://github.com/uilibs/uiprotect/commit/574a846ff4e34737169b49ec418b4a112fa12f3e))


## v1.20.0 (2024-06-21)

### Feature


- Include getter builder utils for fetching ufp object values (#95) ([`9056edf`](https://github.com/uilibs/uiprotect/commit/9056edf85ecf8cd59d053411ae18f1d05093d9e5))


## v1.19.3 (2024-06-21)

### Fix


- Pin and drop pydantic compat imports now that pydantic is fixed (#94) ([`00adc2c`](https://github.com/uilibs/uiprotect/commit/00adc2cc39cf004e93952a8ef489ef1051c1fb83))


## v1.19.2 (2024-06-20)

### Fix


- Ensure update_from_dict creates the object is it was previously none (#93) ([`f268c01`](https://github.com/uilibs/uiprotect/commit/f268c01bac2b9969f10de70dae2295ce87a6f70b))


## v1.19.1 (2024-06-19)

### Fix


- Update broken documentation readme link (#90) ([`1580c04`](https://github.com/uilibs/uiprotect/commit/1580c042d04d989e1ebe4b919df3d232ae4e8ae9))


## v1.19.0 (2024-06-17)

### Feature


- Simplify websocket stats logic (#88) ([`5b01f34`](https://github.com/uilibs/uiprotect/commit/5b01f34b9c5cc8bcb3cae9f274acd687870a4091))


### Fix


- Refactoring error in 83 (#89) ([`ed477c2`](https://github.com/uilibs/uiprotect/commit/ed477c288047fd1fba39f51d6e695adb6a72ba08))


## v1.18.1 (2024-06-17)

### Fix


- Ensure camera and chime keys are not included in the base ignored set (#86) ([`02ab5f6`](https://github.com/uilibs/uiprotect/commit/02ab5f696db9497610ec6b34739452abdfe6ca68))


- Ignore cameraids for chime updates (#85) ([`3a7e48d`](https://github.com/uilibs/uiprotect/commit/3a7e48dea4111eb6b0a6012ffe08cafcd66cf4d6))


## v1.18.0 (2024-06-17)

### Feature


- Add repr for websocket packets (#84) ([`60dd356`](https://github.com/uilibs/uiprotect/commit/60dd356a233ab183c31375417ded3f6e53427e5d))


### Refactor


- Avoid writing out some more key converts (#83) ([`851c798`](https://github.com/uilibs/uiprotect/commit/851c7987b772a185fd4c448dddd9e180fd4f16da))


## v1.17.0 (2024-06-17)

### Feature


- Improve performance of websocket packet processing (#82) ([`58df1c3`](https://github.com/uilibs/uiprotect/commit/58df1c3ac1c050c418d6ea6255ce18ad64422168))


### Refactor


- Remove and consolidate unused code in base (#81) ([`523d931`](https://github.com/uilibs/uiprotect/commit/523d931f6a06b7c66fc7af7cdfac2abf8ebaa737))


- Use tuples for all the delete iterators (#80) ([`9ec88ce`](https://github.com/uilibs/uiprotect/commit/9ec88ce68ab5c0d9f6cb30175eb4ffd9b4a47d43))


- Cleanup debug (#79) ([`7883c24`](https://github.com/uilibs/uiprotect/commit/7883c24c9b9a08e41ec044e943e6fab3b66a56f1))


- Reduce code to remove keys (#78) ([`7b496cb`](https://github.com/uilibs/uiprotect/commit/7b496cb72b3b5efffad18bb86f58355e910122e7))


## v1.16.0 (2024-06-17)

### Feature


- Refactor protect obj methods to use comprehensions (#77) ([`ae4cdb9`](https://github.com/uilibs/uiprotect/commit/ae4cdb914b162c756f8384c0c25f256fbaa634d7))


## v1.15.0 (2024-06-17)

### Feature


- Small cleanup to get device functions (#76) ([`86f18d8`](https://github.com/uilibs/uiprotect/commit/86f18d8901d8fd9b6e2ebfa9c3926ed1d1d0e45c))


## v1.14.0 (2024-06-17)

### Feature


- Optimize update_from_dict (#75) ([`1b8ed6d`](https://github.com/uilibs/uiprotect/commit/1b8ed6dc146c0351927eeb15c47373481b3ad40e))


## v1.13.0 (2024-06-16)

### Feature


- Improve performance of processing websocket messages (#74) ([`84277cb`](https://github.com/uilibs/uiprotect/commit/84277cb3ac8b47e8d6b483ace8e31c0d9b07baad))


## v1.12.1 (2024-06-16)

### Fix


- Ensure ping back messages are called back and empty updates excluded (#62) ([`b319dba`](https://github.com/uilibs/uiprotect/commit/b319dba4b88e0a7d7b237ec57f2e89ca46c1cc6c))


## v1.12.0 (2024-06-16)

### Fix


- Add missing eventstats key to stats_keys (#73) ([`6c8be31`](https://github.com/uilibs/uiprotect/commit/6c8be3129c763d6ade16c57df01cc79d57190fef))


### Feature


- Small cleanups to bootstrap code (#72) ([`78e6dbb`](https://github.com/uilibs/uiprotect/commit/78e6dbb8165b97522b7f42d8f9e885f0e23cd1eb))


## v1.11.1 (2024-06-16)

### Fix


- Revert to using protected attrs for property cache (#71) ([`f0b259c`](https://github.com/uilibs/uiprotect/commit/f0b259caaf7c990de68f1a51a0bd166f94eb3bf7))


## v1.11.0 (2024-06-16)

### Feature


- Speed up bootstrap by adding cached_property (#68) ([`c6b746d`](https://github.com/uilibs/uiprotect/commit/c6b746d8e4d961c0fc1f98d693357e9becd26baa))


## v1.10.0 (2024-06-16)

### Feature


- Make websocket dataclasses sloted (#67) ([`58e42f6`](https://github.com/uilibs/uiprotect/commit/58e42f69b7603ab77ffe170d091051febe22e48f))


## v1.9.0 (2024-06-15)

### Feature


- Improve performance of websocket message processing (#66) ([`d6a6472`](https://github.com/uilibs/uiprotect/commit/d6a6472d3516e27dcfdd2ed3b5d8ca68428e273f))


## v1.8.0 (2024-06-15)

### Feature


- Replace some attrs with cached methods (#65) ([`fc0fc57`](https://github.com/uilibs/uiprotect/commit/fc0fc5717a171eb705dce4f88dca79509bd889b4))


### Refactor


- Delete unused bootstrap constants (#64) ([`0283c45`](https://github.com/uilibs/uiprotect/commit/0283c4564c905bee1b1f82cc4c0280a02e07ec5d))


- Small cleanups to _process_add_packet (#63) ([`8fd8280`](https://github.com/uilibs/uiprotect/commit/8fd82800b63c7cb8c70da164dcc3e1853fc170a6))


## v1.7.2 (2024-06-14)

### Fix


- Pingback did not hold a strong reference to the task (#61) ([`7b11ce9`](https://github.com/uilibs/uiprotect/commit/7b11ce952a9e2f66fc5ac9ceccd1a21e74c218b9))


## v1.7.1 (2024-06-14)

### Fix


- Refactoring error in _process_add_packet (#60) ([`e21516b`](https://github.com/uilibs/uiprotect/commit/e21516b212762955a49d6da66f2f823a1b252ca2))


## v1.7.0 (2024-06-14)

### Feature


- Add debug logging when saving device changes (#59) ([`1c57d00`](https://github.com/uilibs/uiprotect/commit/1c57d005f8f97c148b70401256929c262ba5a8a1))


### Refactor


- Cleanup duplicate doorbell text code (#58) ([`5e3fac8`](https://github.com/uilibs/uiprotect/commit/5e3fac8b862dfe7df83fe7b5b565578f494b8bf1))


## v1.6.0 (2024-06-14)

### Feature


- Simplify object conversions (#55) ([`feb8236`](https://github.com/uilibs/uiprotect/commit/feb8236d7e1817a604186a493d57511fff455e47))


## v1.5.0 (2024-06-14)

### Feature


- Make audio_type a cached_property (#54) ([`50d22de`](https://github.com/uilibs/uiprotect/commit/50d22de5bbf03328c307c7710015e6ec62ab6826))


## v1.4.1 (2024-06-14)

### Fix


- Use none instead of ... for privateattr (#53) ([`fc06f42`](https://github.com/uilibs/uiprotect/commit/fc06f420b6c4531dd59bfa3db8b53a965409cac0))


## v1.4.0 (2024-06-14)

### Feature


- Only process incoming websocket packet model type once (#52) ([`57d7c10`](https://github.com/uilibs/uiprotect/commit/57d7c10d3915fbf45dd81a855298530a36b9e3c7))


## v1.3.0 (2024-06-13)

### Feature


- Cleanup duplicate object lookups in event processing (#51) ([`ec00121`](https://github.com/uilibs/uiprotect/commit/ec001218a39f7ec10bcc18005e59a1130f16f8aa))


## v1.2.2 (2024-06-13)

### Fix


- Restore some unreachable code in _process_device_update (#50) ([`c638cd3`](https://github.com/uilibs/uiprotect/commit/c638cd3b087d63279bd8f798bd8831fc2e11a916))


## v1.2.1 (2024-06-13)

### Fix


- Blocking i/o in the event loop (#49) ([`36a4355`](https://github.com/uilibs/uiprotect/commit/36a4355170566b9d7cfb1632d9c35c28b693d9ce))


## v1.2.0 (2024-06-13)

### Feature


- Avoid fetching and iterating convert keys when empty (#48) ([`7c9ae89`](https://github.com/uilibs/uiprotect/commit/7c9ae89ed667bbe3e9ca2f5561489d4b8335180e))


### Style


- Remove ide workspace files and add the directories for them to the gitignore (#47) ([`486e3f9`](https://github.com/uilibs/uiprotect/commit/486e3f92f4d12ab195f0433e599c9eac0f008aef))


## v1.1.0 (2024-06-12)

### Feature


- Remove _get_frame_data helper (#45) ([`21d6768`](https://github.com/uilibs/uiprotect/commit/21d6768132d553cc9f59e73cc7adbfde02a42915))


### Refactor


- Consolidate logic to remove keys (#44) ([`9da56d2`](https://github.com/uilibs/uiprotect/commit/9da56d2c0f094d31b0cf8cba07c4c07fd96c64ea))


- Use new _event_is_in_range helper in _process_camera_event (#43) ([`49e0a67`](https://github.com/uilibs/uiprotect/commit/49e0a67c5f2473ae1a6bfbe3db513a77786a68df))


- Reduce duplicate code to process sensor events (#41) ([`78c291b`](https://github.com/uilibs/uiprotect/commit/78c291b76a0cbce1f891f91c9c01236d71edbf81))


## v1.0.1 (2024-06-11)

### Fix


- New cookie flag preventing auth cookie from being stored (#36) ([`b6eb7fc`](https://github.com/uilibs/uiprotect/commit/b6eb7fcef23885d734ba0f9031bf15bdbba91bc5))


## v1.0.0 (2024-06-11)

### Breaking


- Remove unused is_ready property from the api client (#33) ([`c36ee42`](https://github.com/uilibs/uiprotect/commit/c36ee422ddd04f811019d2e99cbb1d6b398eae01))


### Refactor


- Use internal self._api inside the object (#34) ([`c20e7a9`](https://github.com/uilibs/uiprotect/commit/c20e7a9690a15f42ff0f17105141f21b2e6e4020))


## v0.15.1 (2024-06-11)

### Fix


- Missing url param in websocket disconnected error log message (#32) ([`60e6511`](https://github.com/uilibs/uiprotect/commit/60e651110ed935bb0c35b09aedbc2253a73c35a4))


## v0.15.0 (2024-06-11)

### Feature


- Cache bootstrap on the protectapiclient once it has been initialized (#31) ([`185e47f`](https://github.com/uilibs/uiprotect/commit/185e47fed693c5a6f8383cece10c5267dbb7e046))


## v0.14.0 (2024-06-11)

### Feature


- Cache parsing of datetimes (#29) ([`8b6747a`](https://github.com/uilibs/uiprotect/commit/8b6747ae41d483da7395f49e402e29f68112fe83))


### Refactor


- Use f-strings in more places (#28) ([`22706c8`](https://github.com/uilibs/uiprotect/commit/22706c896121eac3b6847a951ef516f350119072))


## v0.13.0 (2024-06-11)

### Feature


- Cleanup processing camera events (#27) ([`2c1a266`](https://github.com/uilibs/uiprotect/commit/2c1a266a3f7c290e4ae9724642eb427ca41cabf1))


## v0.12.0 (2024-06-11)

### Feature


- Cleanup websocket add/remove packet processing (#25) ([`fdf0f6e`](https://github.com/uilibs/uiprotect/commit/fdf0f6eef96c17c0d2afe008444c24ce8fad72ee))


- Use a single function to normalize mac addresses (#26) ([`7ce8654`](https://github.com/uilibs/uiprotect/commit/7ce86543d4ec1efa9143839b1b7be1c6dd977ca1))


## v0.11.0 (2024-06-11)

### Feature


- Cleanup processing of websocket packets (#24) ([`b59e19c`](https://github.com/uilibs/uiprotect/commit/b59e19c13ea48e5ab235090c1b02d8d73c3aac24))


## v0.10.1 (2024-06-11)

### Fix


- Remove useless time check (#23) ([`749cfef`](https://github.com/uilibs/uiprotect/commit/749cfef9b44f87397153977c673c577659450a48))


## v0.10.0 (2024-06-11)

### Feature


- Improve performance of process websocket packets (#22) ([`7b59c98`](https://github.com/uilibs/uiprotect/commit/7b59c98d02d2f874375b168979a1db253da58914))


## v0.9.0 (2024-06-10)

### Feature


- Avoid linear searches to process websocket packets (#21) ([`86d5f19`](https://github.com/uilibs/uiprotect/commit/86d5f198071b0478b480804d055ed80c88341ee1))


## v0.8.0 (2024-06-10)

### Feature


- Guard debug logging that reformats data in the arguments (#20) ([`0cfdea8`](https://github.com/uilibs/uiprotect/commit/0cfdea8d27c0a35d71cd98d65120288218f4ca4c))


### Refactor


- Remove useless .keys() calls (#19) ([`ec1fd12`](https://github.com/uilibs/uiprotect/commit/ec1fd129deb06b5d2334d49ccd0b238033c5b904))


## v0.7.0 (2024-06-10)

### Feature


- Refactor protect object subtype bucketing (#18) ([`e4123ac`](https://github.com/uilibs/uiprotect/commit/e4123ac13015c186f141c1bfec3a7c064bb2d732))


## v0.6.0 (2024-06-10)

### Feature


- Small code cleanups (#17) ([`f1668ae`](https://github.com/uilibs/uiprotect/commit/f1668ae2c9c9f49f6e703a387159d305c2cba847))


## v0.5.0 (2024-06-10)

### Feature


- Memoize enum type check to speed up data conversion (#15) ([`73b0c4a`](https://github.com/uilibs/uiprotect/commit/73b0c4a813e99d3f353a8fbf3d8a997158cedf3a))


## v0.4.1 (2024-06-10)

### Fix


- Handle unifi os 4 token change (#14) ([`a6aab8f`](https://github.com/uilibs/uiprotect/commit/a6aab8f1eefd631119288f6d29d643f3984c5b0d))


## v0.4.0 (2024-06-10)

### Feature


- Avoid parsing last_update_id (#12) ([`ac86b13`](https://github.com/uilibs/uiprotect/commit/ac86b13b3efc8fc619471536ea993f3741882264))


## v0.3.10 (2024-06-10)

### Fix


- Add missing doorbellmessagetype image (#11) ([`eaed04b`](https://github.com/uilibs/uiprotect/commit/eaed04bbc1697553895a64edc573d1acc9112a1a))


## v0.3.9 (2024-06-09)

### Fix


- Revert global flags check (#9) ([`8dc437f`](https://github.com/uilibs/uiprotect/commit/8dc437f38dc4f6f6081d9a8a80f9f295b31bf579))


## v0.3.8 (2024-06-09)

### Fix


- Improve readme and testdata docs (#8) ([`90ae6a8`](https://github.com/uilibs/uiprotect/commit/90ae6a8cec7a10c1631b301a5d64c94bffdee16d))


## v0.3.7 (2024-06-09)

### Fix


- Revert pydantic changes for ha compat (#7) ([`c7770c1`](https://github.com/uilibs/uiprotect/commit/c7770c135deaa52da078794c67d5e3f5dbe3455d))


## v0.3.6 (2024-06-09)

### Fix


- Switch readthedocs to mkdocs ([`6009f9d`](https://github.com/uilibs/uiprotect/commit/6009f9dbb5beed141a8af866eb6e1dfd081af067))


- More docs fixes ([`52261ef`](https://github.com/uilibs/uiprotect/commit/52261eff11919768d75e73f9f3a85243c7eff90a))


## v0.3.5 (2024-06-09)

### Fix


- Add missing docs deps ([`399de45`](https://github.com/uilibs/uiprotect/commit/399de45721cb72c1cd6c945ad9aa0d73d82dea8f))


## v0.3.4 (2024-06-09)

### Fix


- Small fixes for readme.md (#6) ([`7a0acf4`](https://github.com/uilibs/uiprotect/commit/7a0acf4da9cfcc1cbf6111cc9d2083be68aa9d93))


## v0.3.3 (2024-06-09)

### Fix


- Ensure uv is installed for docker image ([`d286198`](https://github.com/uilibs/uiprotect/commit/d286198ce4d26ff5151c9b937058b4c223aa95f2))


## v0.3.2 (2024-06-09)

### Fix


- Docker file ([`8474862`](https://github.com/uilibs/uiprotect/commit/84748626bbe29492997801759164a6242ebf7b72))


- Update typer ([`54f26b1`](https://github.com/uilibs/uiprotect/commit/54f26b16223d0ed83c2e249df458ec5ccc407fb6))


- Make package installable ([`169e790`](https://github.com/uilibs/uiprotect/commit/169e7903bc72ad513f475c5477c0b6f4cd5c7653))


## v0.3.1 (2024-06-09)

### Fix


- Dockerfile ([`b25d8a1`](https://github.com/uilibs/uiprotect/commit/b25d8a1218158368ec50d1a2b20280b94696ccee))


- Docker ci (#5) ([`3d8e9fe`](https://github.com/uilibs/uiprotect/commit/3d8e9fe294c7c75a7efc2d2653a51fdb052fbf29))


## v0.3.0 (2024-06-09)

### Feature


- Migrate docs (#4) ([`1e62ec2`](https://github.com/uilibs/uiprotect/commit/1e62ec204c6d1b26f95486a8c27a61bb40a8219b))


## v0.2.2 (2024-06-09)

### Fix


- Readme updates (#3) ([`8cf5d24`](https://github.com/uilibs/uiprotect/commit/8cf5d24915e9aed2ffbdce4390dd061c9c40d4a1))


## v0.2.1 (2024-06-09)

### Fix


- Adjust jinja check for changelog template ([`e5f55c1`](https://github.com/uilibs/uiprotect/commit/e5f55c1f1af84d3f9053bf9b36c3662dab706882))


- Changelog generation (#2) ([`2b770e9`](https://github.com/uilibs/uiprotect/commit/2b770e9a4a6ccfa352fd0fc2b30099ef07b59db8))


## v0.2.0 (2024-06-09)

### Feature


- Update classifiers (#1) ([`0d4eaf6`](https://github.com/uilibs/uiprotect/commit/0d4eaf6e5fe30c83c52d30d388d65ebe33ee7c3f))


### Unknown



### Fix


- Re-enable changelog ([`68620b0`](https://github.com/uilibs/uiprotect/commit/68620b09b65ee553982c2c54bfc1e0a3c6ba4380))


## v0.1.0 (2024-06-09)

### Fix


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
















































































































































































































































































































































































































































































































































































































































































































































































































































































### Fix


- Actually set chime_duration ([`e7edd26`](https://github.com/uilibs/uiprotect/commit/e7edd26823505f73e97b1a46e70f397a95126a3f))


### Feature


- Make chime duration adjustable ([`b4d13c1`](https://github.com/uilibs/uiprotect/commit/b4d13c146f292eae216109f747d3bee6608b0f28))

