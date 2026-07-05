# API Reference

## Start generating

These endpoints all kick off tasks to create generations.

## Image to video

`POST /v1/image_to_video`

This endpoint will start a new task to generate a video from an image.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`model` *(required)* `string`
Fields change based on which value is passed. Select which value to show documentation for.`gen4.5`, `gen4_turbo`, `gen3a_turbo`, `veo3.1`, `veo3.1_fast`, `veo3`

`promptText` *(required)* `string` [ 1 .. 1000 ] characters
A non-empty string up to 1000 characters (measured in UTF-16 code units). This should describe in detail what should appear in the output.

`promptImage` *(required)* `string or Array of PromptImages (objects)`
One of the following shapes: `string` A HTTPS URL, Runway or data URI containing an encoded image. See [our docs](/assets/inputs#images) on image inputs for more information.

One of the following shapes: `string` [ 13 .. 2048 ] characters ^https:\/\/.* A HTTPS URL.

`string` [ 13 .. 5000 ] characters ^runway:\/\/.* A Runway upload URI. See [https://docs.dev.runwayml.com/assets/uploads](https://docs.dev.runwayml.com/assets/uploads) for more information.

`string` [ 13 .. 5242880 ] characters ^data:image\/.* A data URI containing encoded media.

`PromptImages`Array of `objects` = 1 items `uri` *(required)* `string`
A HTTPS URL, Runway or data URI containing an encoded image. See [our docs](/assets/inputs#images) on image inputs for more information.

One of the following shapes: `string` [ 13 .. 2048 ] characters ^https:\/\/.* A HTTPS URL.

`string` [ 13 .. 5000 ] characters ^runway:\/\/.* A Runway upload URI. See [https://docs.dev.runwayml.com/assets/uploads](https://docs.dev.runwayml.com/assets/uploads) for more information.

`string` [ 13 .. 5242880 ] characters ^data:image\/.* A data URI containing encoded media.

`position` *(required)* `string`
The position of the image in the output video. "first" will use the image as the first frame of the video.

This field must be set to the exact value `first`.

`ratio` *(required)* `string`
Accepted values:"1280:720", "720:1280", "1104:832", "960:960", "832:1104", "1584:672" The resolution of the output video.

`duration` *(required)* `integer` [ 2 .. 10 ]
The number of seconds of duration for the output video. Must be an integer from 2 to 10.

`seed` `integer` [ 0 .. 4294967295 ]
If unspecified, a random number is chosen. Varying the seed integer is a way to get different results for the same other request parameters. Using the same seed integer for an identical request will produce similar results.

`contentModeration` `object`
Settings that affect the behavior of the content moderation system.

`publicFigureThreshold` `string`
Accepted values:"auto", "low" When set to `low`, the content moderation system will be less strict about preventing generations that include recognizable public figures.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

task = client.image_to_video.create(
model='gen4_turbo',
prompt_image='https://example.com/bunny.jpg',
prompt_text='A cute bunny hopping in a meadow',
duration=10,
).wait_for_task_output()

print(task)
```

```json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08"}
```

## Text to video

`POST /v1/text_to_video`

This endpoint will start a new task to generate a video from a text prompt.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`model` *(required)* `string`
Fields change based on which value is passed. Select which value to show documentation for.`gen4.5`, `veo3.1`, `veo3.1_fast`, `veo3`

`promptText` *(required)* `string` [ 1 .. 1000 ] characters
A non-empty string up to 1000 characters (measured in UTF-16 code units). This should describe in detail what should appear in the output.

`ratio` *(required)* `string`
Accepted values:"1280:720", "720:1280" The resolution of the output video.

`duration` *(required)* `integer` [ 2 .. 10 ]
The number of seconds of duration for the output video. Must be an integer from 2 to 10.

`seed` `integer` [ 0 .. 4294967295 ]
If unspecified, a random number is chosen. Varying the seed integer is a way to get different results for the same other request parameters. Using the same seed integer for an identical request will produce similar results.

`contentModeration` `object`
Settings that affect the behavior of the content moderation system.

`publicFigureThreshold` `string`
Accepted values:"auto", "low" When set to `low`, the content moderation system will be less strict about preventing generations that include recognizable public figures.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

task = client.text_to_video.create(
model='veo3.1',
prompt_text='A cute bunny hopping in a meadow',
ratio='1280:720',
duration=8,
).wait_for_task_output()

print(task)
```

```json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08"}
```

## Video to video

`POST /v1/video_to_video`

This endpoint will start a new task to generate a video from a video.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`model` *(required)* `string`
This field must be set to the exact value `gen4_aleph`.

`videoUri` *(required)* `string`
A HTTPS URL, Runway or data URI containing an encoded video. See [our docs](/assets/inputs#videos) on video inputs for more information.

One of the following shapes: `string` [ 13 .. 2048 ] characters ^https:\/\/.* A HTTPS URL.

`string` [ 13 .. 5000 ] characters ^runway:\/\/.* A Runway upload URI. See [https://docs.dev.runwayml.com/assets/uploads](https://docs.dev.runwayml.com/assets/uploads) for more information.

`string` [ 13 .. 16777216 ] characters ^data:video\/.* A data URI containing encoded media.

`promptText` *(required)* `string` [ 1 .. 1000 ] characters
A non-empty string up to 1000 characters (measured in UTF-16 code units). This should describe in detail what should appear in the output.

`seed` `integer` [ 0 .. 4294967295 ]
If unspecified, a random number is chosen. Varying the seed integer is a way to get different results for the same other request parameters. Using the same seed integer for an identical request will produce similar results.

`references` `ImageReference (object)`
An array of references. Currently up to one reference is supported. See [our docs](/assets/inputs#images) on image inputs for more information.

`ImageReference` `object` Passing an image reference allows the model to emulate the style or content of the reference in the output.

`type` *(required)* `string`
This field must be set to the exact value `image`.

`uri` *(required)* `string`
A HTTPS URL, Runway or data URI containing an encoded image. See [our docs](/assets/inputs#images) on image inputs for more information.

One of the following shapes: `string` [ 13 .. 2048 ] characters ^https:\/\/.* A HTTPS URL.

`string` [ 13 .. 5000 ] characters ^runway:\/\/.* A Runway upload URI. See [https://docs.dev.runwayml.com/assets/uploads](https://docs.dev.runwayml.com/assets/uploads) for more information.

`string` [ 13 .. 5242880 ] characters ^data:image\/.* A data URI containing encoded media.

`contentModeration` `object`
Settings that affect the behavior of the content moderation system.

`publicFigureThreshold` `string`
Accepted values:"auto", "low" When set to `low`, the content moderation system will be less strict about preventing generations that include recognizable public figures.

`ratio` `string`
Deprecated Accepted values:"1280:720", "720:1280", "1104:832", "960:960", "832:1104", "1584:672", "848:480", "640:480" Deprecated. This field is ignored. The resolution of the output video is determined by the input video.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

task = client.video_to_video.create(
model='gen4_aleph',
video_uri='https://example.com/bunny.mp4',
prompt_text='string',
references=[
{
'type': 'image',
'uri': 'https://example.com/easter-scene.jpg',
},
],
ratio='1280:720',
).wait_for_task_output()

print(task)
```

```json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08"}
```

## Text/Image to Image

`POST /v1/text_to_image`

This endpoint will start a new task to generate images from text and/or image(s)

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`model` *(required)* `string`
Fields change based on which value is passed. Select which value to show documentation for.`gen4_image_turbo`, `gen4_image`, `gemini_2.5_flash`

`promptText` *(required)* `string` [ 1 .. 1000 ] characters
A non-empty string up to 1000 characters (measured in UTF-16 code units). This should describe in detail what should appear in the output.

`ratio` *(required)* `string`
Accepted values:"1024:1024", "1080:1080", "1168:880", "1360:768", "1440:1080", "1080:1440", "1808:768", "1920:1080", "1080:1920", "2112:912", "1280:720", "720:1280", "720:720", "960:720", "720:960", "1680:720" The resolution of the output image.

`referenceImages` *(required)* `objects` [ 1 .. 3 ] items
An array of one to three images to be used as references for the generated image output.

`uri` *(required)* `string`
A HTTPS URL, Runway or data URI containing an encoded image. See [our docs](/assets/inputs#images) on image inputs for more information.

One of the following shapes: `string` [ 13 .. 2048 ] characters ^https:\/\/.* A HTTPS URL.

`string` [ 13 .. 5000 ] characters ^runway:\/\/.* A Runway upload URI. See [https://docs.dev.runwayml.com/assets/uploads](https://docs.dev.runwayml.com/assets/uploads) for more information.

`string` [ 13 .. 5242880 ] characters ^data:image\/.* A data URI containing encoded media.

`tag` `string` [ 3 .. 16 ] characters
A tag to identify the reference image. This is used to reference the image in prompt text.

`seed` `integer` [ 0 .. 4294967295 ]
If unspecified, a random number is chosen. Varying the seed integer is a way to get different results for the same other request parameters. Using the same seed integer for an identical request will produce similar results.

`contentModeration` `object`
Settings that affect the behavior of the content moderation system.

`publicFigureThreshold` `string`
Accepted values:"auto", "low" When set to `low`, the content moderation system will be less strict about preventing generations that include recognizable public figures.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

task = client.text_to_image.create(
model='gen4_image',
prompt_text='A serene landscape with mountains',
ratio='1360:768',
).wait_for_task_output()

print(task)
```

```json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08"}
```

## Control a character

`POST /v1/character_performance`

This endpoint will start a new task to control a character's facial expressions and body movements using a reference video.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`model` *(required)* `string`
This field must be set to the exact value `act_two`.

`character` *(required)* `CharacterImage (object) or CharacterVideo (object)`
The character to control. You can either provide a video or an image. A visually recognizable face must be visible and stay within the frame.

One of the following shapes:`CharacterImage` `object` An image of your character. In the output, the character will use the reference video performance in its original static environment.

`type` *(required)* `string`
This field must be set to the exact value `image`.

`uri` *(required)* `string`
A HTTPS URL, Runway or data URI containing an encoded image. See [our docs](/assets/inputs#images) on image inputs for more information.

One of the following shapes: `string` [ 13 .. 2048 ] characters ^https:\/\/.* A HTTPS URL.

`string` [ 13 .. 5000 ] characters ^runway:\/\/.* A Runway upload URI. See [https://docs.dev.runwayml.com/assets/uploads](https://docs.dev.runwayml.com/assets/uploads) for more information.

`string` [ 13 .. 5242880 ] characters ^data:image\/.* A data URI containing encoded media.

`CharacterVideo` `object` A video of your character. In the output, the character will use the reference video performance in its original animated environment and some of the character's own movements.

`type` *(required)* `string`
This field must be set to the exact value `video`.

`uri` *(required)* `string`
A HTTPS URL, Runway or data URI containing an encoded video. See [our docs](/assets/inputs#videos) on video inputs for more information.

One of the following shapes: `string` [ 13 .. 2048 ] characters ^https:\/\/.* A HTTPS URL.

`string` [ 13 .. 5000 ] characters ^runway:\/\/.* A Runway upload URI. See [https://docs.dev.runwayml.com/assets/uploads](https://docs.dev.runwayml.com/assets/uploads) for more information.

`string` [ 13 .. 16777216 ] characters ^data:video\/.* A data URI containing encoded media.

`reference` *(required)* `CharacterReferenceVideo (object)`
The reference video containing the performance to apply to the character.

`CharacterReferenceVideo` `object` A video of a person performing in the manner that you would like your character to perform. The video must be between 3 and 30 seconds in duration.

`type` *(required)* `string`
This field must be set to the exact value `video`.

`uri` *(required)* `string`
A video of a person performing in the manner that you would like your character to perform. The video must be between 3 and 30 seconds in duration. See [our docs](/assets/inputs#videos) on video inputs for more information.

One of the following shapes: `string` [ 13 .. 2048 ] characters ^https:\/\/.* A HTTPS URL.

`string` [ 13 .. 5000 ] characters ^runway:\/\/.* A Runway upload URI. See [https://docs.dev.runwayml.com/assets/uploads](https://docs.dev.runwayml.com/assets/uploads) for more information.

`string` [ 13 .. 16777216 ] characters ^data:video\/.* A data URI containing encoded media.

`seed` `integer` [ 0 .. 4294967295 ]
If unspecified, a random number is chosen. Varying the seed integer is a way to get different results for the same other request parameters. Using the same seed integer for an identical request will produce similar results.

`bodyControl` `boolean`
A boolean indicating whether to enable body control. When enabled, non-facial movements and gestures will be applied to the character in addition to facial expressions.

`expressionIntensity` `integer` [ 1 .. 5 ]
Default:3 An integer between 1 and 5 (inclusive). A larger value increases the intensity of the character's expression.

`ratio` `string`
Accepted values:"1280:720", "720:1280", "960:960", "1104:832", "832:1104", "1584:672" The resolution of the output video.

`contentModeration` `object`
Settings that affect the behavior of the content moderation system.

`publicFigureThreshold` `string`
Accepted values:"auto", "low" When set to `low`, the content moderation system will be less strict about preventing generations that include recognizable public figures.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

task = client.character_performance.create(
model='act_two',
character={
'type': 'video',
'uri': 'https://example.com/posedCharacter.mp4',
},
reference={
'type': 'video',
'uri': 'https://example.com/actorPerformance.mp4',
},
ratio='1280:720',
).wait_for_task_output()

print(task)
```

```json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08"}
```

## Generate sound effects

`POST /v1/sound_effect`

This endpoint will start a new task to generate sound effects from a text description.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`model` *(required)* `string`
This field must be set to the exact value `eleven_text_to_sound_v2`.

`promptText` *(required)* `string` [ 1 .. 3000 ] characters
A text description of the sound effect to generate.

`duration` `number` [ 0.5 .. 30 ]
The duration of the sound effect in seconds, between 0.5 and 30 seconds. If not provided, the duration will be determined automatically based on the text description.

`loop` `boolean`
Default:false Whether the output sound effect should be designed to loop seamlessly.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

task = client.sound_effect.create(
model='eleven_text_to_sound_v2',
promptText='A thunderstorm with heavy rain',
duration=10,
loop=True,
).wait_for_task_output()

print(task)
```

```json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08"}
```

## Speech to speech

`POST /v1/speech_to_speech`

This endpoint will start a new task to convert speech from one voice to another in audio or video.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`model` *(required)* `string`
This field must be set to the exact value `eleven_multilingual_sts_v2`.

`media` *(required)* `SpeechToSpeechAudio (object) or SpeechToSpeechVideo (object)`
One of the following shapes:`SpeechToSpeechAudio` `object` An audio file containing dialogue to be processed.

`type` *(required)* `string`
This field must be set to the exact value `audio`.

`uri` *(required)* `string`
A HTTPS URL, Runway or data URI containing an encoded audio. See [our docs](/assets/inputs#audio) on audio inputs for more information.

One of the following shapes: `string` [ 13 .. 2048 ] characters ^https:\/\/.* A HTTPS URL.

`string` [ 13 .. 5000 ] characters ^runway:\/\/.* A Runway upload URI. See [https://docs.dev.runwayml.com/assets/uploads](https://docs.dev.runwayml.com/assets/uploads) for more information.

`string` [ 13 .. 16777216 ] characters ^data:audio\/.* A data URI containing encoded media.

`SpeechToSpeechVideo` `object` A video file containing dialogue to be processed.

`type` *(required)* `string`
This field must be set to the exact value `video`.

`uri` *(required)* `string`
A HTTPS URL, Runway or data URI containing an encoded video. See [our docs](/assets/inputs#videos) on video inputs for more information.

One of the following shapes: `string` [ 13 .. 2048 ] characters ^https:\/\/.* A HTTPS URL.

`string` [ 13 .. 5000 ] characters ^runway:\/\/.* A Runway upload URI. See [https://docs.dev.runwayml.com/assets/uploads](https://docs.dev.runwayml.com/assets/uploads) for more information.

`string` [ 13 .. 16777216 ] characters ^data:video\/.* A data URI containing encoded media.

`voice` *(required)* `RunwayPresetVoice (object)`
The voice to use for the generated speech.

`RunwayPresetVoice` `object` A voice preset from the RunwayML API.

`type` *(required)* `string`
This field must be set to the exact value `runway-preset`.

`presetId` *(required)* `string`
Accepted values:"Maya", "Arjun", "Serene", "Bernard", "Billy", "Mark", "Clint", "Mabel", "Chad", "Leslie", "Eleanor", "Elias", "Elliot", "Grungle", "Brodie", "Sandra", "Kirk", "Kylie", "Lara", "Lisa", "Malachi", "Marlene", "Martin", "Miriam", "Monster", "Paula", "Pip", "Rusty", "Ragnar", "Xylar", "Maggie", "Jack", "Katie", "Noah", "James", "Rina", "Ella", "Mariah", "Frank", "Claudia", "Niki", "Vincent", "Kendrick", "Myrna", "Tom", "Wanda", "Benjamin", "Kiana", "Rachel" The preset voice ID to use for the generated speech.

`removeBackgroundNoise` `boolean`
Whether to remove background noise from the generated speech.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

audioTask = client.speech_to_speech.create(
model='eleven_multilingual_sts_v2',
media={
'type': 'audio',
'uri': 'https://example.com/audio.mp3',
},
voice={
'type': 'runway-preset',
'presetId': 'Maggie',
},
).wait_for_task_output()

print(audioTask)

videoTask = client.speech_to_speech.create(
model='eleven_multilingual_sts_v2',
media={
'type': 'video',
'uri': 'https://example.com/video.mp4',
},
voice={
'type': 'runway-preset',
'presetId': 'Noah',
},
).wait_for_task_output()

print(videoTask)
```

```json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08"}
```

## Text to speech

`POST /v1/text_to_speech`

This endpoint will start a new task to generate speech from text.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`model` *(required)* `string`
This field must be set to the exact value `eleven_multilingual_v2`.

`promptText` *(required)* `string` [ 1 .. 1000 ] characters
A non-empty string up to 1000 characters (measured in UTF-16 code units). This should describe in detail what should appear in the output.

`voice` *(required)* `RunwayPresetVoice (object)`
The voice to use for the generated speech.

`RunwayPresetVoice` `object` A voice preset from the RunwayML API.

`type` *(required)* `string`
This field must be set to the exact value `runway-preset`.

`presetId` *(required)* `string`
Accepted values:"Maya", "Arjun", "Serene", "Bernard", "Billy", "Mark", "Clint", "Mabel", "Chad", "Leslie", "Eleanor", "Elias", "Elliot", "Grungle", "Brodie", "Sandra", "Kirk", "Kylie", "Lara", "Lisa", "Malachi", "Marlene", "Martin", "Miriam", "Monster", "Paula", "Pip", "Rusty", "Ragnar", "Xylar", "Maggie", "Jack", "Katie", "Noah", "James", "Rina", "Ella", "Mariah", "Frank", "Claudia", "Niki", "Vincent", "Kendrick", "Myrna", "Tom", "Wanda", "Benjamin", "Kiana", "Rachel" The preset voice ID to use for the generated speech.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

task = client.text_to_speech.create(
model='eleven_multilingual_v2',
prompt_text='The quick brown fox jumps over the lazy dog',
voice={
'type': 'runway-preset',
'presetId': 'Leslie',
},
).wait_for_task_output()

print(task)
```

```json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08"}
```

## Voice dubbing

`POST /v1/voice_dubbing`

This endpoint will start a new task to dub audio content to a target language.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`model` *(required)* `string`
This field must be set to the exact value `eleven_voice_dubbing`.

`audioUri` *(required)* `string`
A HTTPS URL, Runway or data URI containing an encoded audio. See [our docs](/assets/inputs#audio) on audio inputs for more information.

One of the following shapes: `string` [ 13 .. 2048 ] characters ^https:\/\/.* A HTTPS URL.

`string` [ 13 .. 5000 ] characters ^runway:\/\/.* A Runway upload URI. See [https://docs.dev.runwayml.com/assets/uploads](https://docs.dev.runwayml.com/assets/uploads) for more information.

`string` [ 13 .. 16777216 ] characters ^data:audio\/.* A data URI containing encoded media.

`targetLang` *(required)* `string`
Accepted values:"en", "hi", "pt", "zh", "es", "fr", "de", "ja", "ar", "ru", "ko", "id", "it", "nl", "tr", "pl", "sv", "fil", "ms", "ro", "uk", "el", "cs", "da", "fi", "bg", "hr", "sk", "ta" The target language code to dub the audio to (e.g., "es" for Spanish, "fr" for French).

`disableVoiceCloning` `boolean`
Whether to disable voice cloning and use a generic voice instead.

`dropBackgroundAudio` `boolean`
Whether to remove background audio from the dubbed output.

`numSpeakers` `integer` ( 0 .. 9007199254740991 ]
The number of speakers in the audio. If not provided, it will be detected automatically.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

task = client.voice_dubbing.create(
model='eleven_voice_dubbing',
audio_uri='https://example.com/audio.mp3',
target_lang='es',
).wait_for_task_output()

print(task)
```

```json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08"}
```

## Voice isolation

`POST /v1/voice_isolation`

This endpoint will start a new task to isolate the voice from the background audio. Audio duration must be greater than 4.6 seconds and less than 3600 seconds.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`model` *(required)* `string`
This field must be set to the exact value `eleven_voice_isolation`.

`audioUri` *(required)* `string`
A HTTPS URL, Runway or data URI containing an encoded audio. See [our docs](/assets/inputs#audio) on audio inputs for more information.

One of the following shapes: `string` [ 13 .. 2048 ] characters ^https:\/\/.* A HTTPS URL.

`string` [ 13 .. 5000 ] characters ^runway:\/\/.* A Runway upload URI. See [https://docs.dev.runwayml.com/assets/uploads](https://docs.dev.runwayml.com/assets/uploads) for more information.

`string` [ 13 .. 16777216 ] characters ^data:audio\/.* A data URI containing encoded media.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

task = client.voice_isolation.create(
model='eleven_voice_isolation',
audio_url='https://example.com/audio.mp3',
).wait_for_task_output()

print(task)
```

```json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08"}
```

## Task management

Endpoints for managing tasks that have been submitted.

## Get task detail

`GET /v1/tasks/{id}`

Return details about a task. Consumers of this API should not expect updates more frequent than once every five seconds for a given task.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Path parameters

`id` *(required)* `string`
The ID of a previously-submitted task that has not been canceled or deleted.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

task_id = '17f20503-6c24-4c16-946b-35dbbce2af2f'

# Fetch the current state of the task:
task = client.tasks.retrieve(id=task_id)
print(task)

# Or, wait for the task to succeed or fail:
task = client.tasks.retrieve(id=task_id).wait_for_task_output()
print(task)
```

`An example of a pending task`, `An example of a throttled task`, `An example of a running task`, `An example of a succeeded task`, `An example of a failed task````json
{"id": "17f20503-6c24-4c16-946b-35dbbce2af2f","status": "PENDING","createdAt": "2024-06-27T19:49:32.334Z"}
```

## Cancel or delete a task

`DELETE /v1/tasks/{id}`

Tasks that are running, pending, or throttled can be canceled by invoking this method. Invoking this method for other tasks will delete them.

The output data associated with a deleted task will be deleted from persistent storage in accordance with our data retention policy. Aborted and deleted tasks will not be able to be fetched again in the future.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Path parameters

`id` *(required)* `string`
The ID of a previously-submitted task that has not been canceled or deleted.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

client.tasks.delete(id='17f20503-6c24-4c16-946b-35dbbce2af2f')
```

## Uploads

Endpoints for uploading media files.

## Upload a file

`POST /v1/uploads`

Uploads a temporary media file that can be referenced in API generation requests. The uploaded files will be automatically expired and deleted after a period of time. It is strongly recommended to use our SDKs for this which have a simplified interface that directly accepts file objects.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`filename` *(required)* `string` [ 3 .. 255 ] characters
The filename of the file to upload. Must have a valid extension and be a supported media type (image, video, or audio).

`type` *(required)* `string`
Accepted value:"ephemeral" The type of upload to create

### Responses

```
# pip install runwayml
from runwayml import RunwayML
from pathlib import Path

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

file = Path('./funny-cats.mp4');
upload_uri = client.uploads.create_ephemeral(
file=file,
)

# Use the upload_uri in generation requests
task = client.video_to_video.create(
model='gen4_aleph',
video_uri=upload_uri,
prompt_text='Add the easter elements to the cat video',
references=[
{
'type': 'image',
'uri': 'https://example.com/easter-scene.jpg',
},
],
ratio='1280:720',
).wait_for_task_output()

print(task)
```

```json
{"uploadUrl": "http://example.com","fields": {"property1": "string","property2": "string"},"runwayUri": "string"}
```

## Avatars

## List avatars

`GET /v1/avatars`

List avatars for the authenticated user with cursor-based pagination.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Query parameters

`limit` *(required)* `integer` [ 1 .. 100 ]
Default:50 The maximum number of items to return per page.

`cursor` `string` [ 1 .. 1000 ] characters
Cursor from a previous response for fetching the next page of results.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

for avatar in client.avatars.list():
print(avatar)
```

```json
{"data": [{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08","name": "string","personality": "string","startScript": "string","voice": {"type": "runway-live-preset","presetId": "victoria","name": "string","description": "string"},"referenceImageUri": "string","processedImageUri": "string","documentIds": ["497f6eca-6276-4993-bfeb-53cbbbba6f08"],"createdAt": "2019-08-24T14:15:22Z","updatedAt": "2019-08-24T14:15:22Z","status": "PROCESSING"}],"hasMore": true,"nextCursor": "string"}
```

## Create avatar

`POST /v1/avatars`

Create a new avatar with a reference image and voice.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`name` *(required)* `string` [ 1 .. 50 ] characters
The character name for the avatar.

`referenceImage` *(required)* `string`
A HTTPS URL, Runway URI, or data URI containing the avatar reference image. See [our docs](/assets/inputs#images) for supported formats.

One of the following shapes: `string` [ 13 .. 2048 ] characters ^https:\/\/.* A HTTPS URL.

`string` [ 13 .. 5000 ] characters ^runway:\/\/.* A Runway upload URI. See [https://docs.dev.runwayml.com/assets/uploads](https://docs.dev.runwayml.com/assets/uploads) for more information.

`string` [ 13 .. 5242880 ] characters ^data:image\/.* A data URI containing encoded media.

`personality` *(required)* `string` [ 1 .. 2000 ] characters
System prompt defining how the avatar should behave in conversations.

`voice` *(required)* `RunwayLivePresetVoice (object) or CustomVoice (object)`
The voice configuration for the avatar.

One of the following shapes:`RunwayLivePresetVoice` `object` A preset voice from the Runway API.

`type` *(required)* `string`
This field must be set to the exact value `runway-live-preset`.

`presetId` *(required)* `string`
Accepted values:"victoria", "vincent", "clara", "drew", "skye", "max", "morgan", "felix", "mia", "marcus", "summer", "ruby", "aurora", "jasper", "leo", "adrian", "nina", "emma", "blake", "david", "maya", "nathan", "sam", "georgia", "petra", "adam", "zach", "violet", "roman", "luna" The ID of a preset voice. Available voices: `victoria` (Victoria), `vincent` (Vincent), `clara` (Clara), `drew` (Drew), `skye` (Skye), `max` (Max), `morgan` (Morgan), `felix` (Felix), `mia` (Mia), `marcus` (Marcus), `summer` (Summer), `ruby` (Ruby), `aurora` (Aurora), `jasper` (Jasper), `leo` (Leo), `adrian` (Adrian), `nina` (Nina), `emma` (Emma), `blake` (Blake), `david` (David), `maya` (Maya), `nathan` (Nathan), `sam` (Sam), `georgia` (Georgia), `petra` (Petra), `adam` (Adam), `zach` (Zach), `violet` (Violet), `roman` (Roman), `luna` (Luna).

`CustomVoice` `object` A custom voice created via the Voices API.

`type` *(required)* `string`
This field must be set to the exact value `custom`.

`id` *(required)* `string`
The ID of a custom voice created via the Voices API.

`startScript` `string` <= 2000 characters
Optional opening message that the avatar will say when a session starts.

`documentIds` `strings` <= 50 items
Optional list of knowledge document IDs to attach to this avatar. Documents provide additional context during conversations.

`imageProcessing` `string`
Default:"optimize"Accepted values:"optimize", "none" Controls image preprocessing. `optimize` improves the image for better avatar results. `none` uses the image as-is; quality not guaranteed.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

avatar = client.avatars.create(
name='Customer Support Agent',
reference_image='https://example.com/reference.jpg',
personality='You are a helpful customer support agent. Be friendly and concise.',
voice={ 'type': 'runway-live-preset', 'preset_id': 'adrian' },
)
print(avatar)
```

`AvatarProcessing`, `AvatarReady`, `AvatarFailed````json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08","name": "string","personality": "string","startScript": "string","voice": {"type": "runway-live-preset","presetId": "victoria","name": "string","description": "string"},"referenceImageUri": "string","processedImageUri": "string","documentIds": ["497f6eca-6276-4993-bfeb-53cbbbba6f08"],"createdAt": "2019-08-24T14:15:22Z","updatedAt": "2019-08-24T14:15:22Z","status": "AvatarProcessing"}
```

## Get avatar

`GET /v1/avatars/{id}`

Get details of a specific avatar.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Path parameters

`id` *(required)* `string`

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

avatar = client.avatars.retrieve(
id='550e8400-e29b-41d4-a716-446655440000'
)
print(avatar)
```

`AvatarProcessing`, `AvatarReady`, `AvatarFailed````json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08","name": "string","personality": "string","startScript": "string","voice": {"type": "runway-live-preset","presetId": "victoria","name": "string","description": "string"},"referenceImageUri": "string","processedImageUri": "string","documentIds": ["497f6eca-6276-4993-bfeb-53cbbbba6f08"],"createdAt": "2019-08-24T14:15:22Z","updatedAt": "2019-08-24T14:15:22Z","status": "AvatarProcessing"}
```

## Update avatar

`PATCH /v1/avatars/{id}`

Update an existing avatar. At least one field must be provided.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Path parameters

`id` *(required)* `string`

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`name` `string` [ 1 .. 50 ] characters
The character name for the avatar.

`referenceImage` `string`
A HTTPS URL, Runway URI, or data URI containing the avatar reference image. See [our docs](/assets/inputs#images) for supported formats.

One of the following shapes: `string` [ 13 .. 2048 ] characters ^https:\/\/.* A HTTPS URL.

`string` [ 13 .. 5000 ] characters ^runway:\/\/.* A Runway upload URI. See [https://docs.dev.runwayml.com/assets/uploads](https://docs.dev.runwayml.com/assets/uploads) for more information.

`string` [ 13 .. 5242880 ] characters ^data:image\/.* A data URI containing encoded media.

`personality` `string` [ 1 .. 2000 ] characters
System prompt defining how the avatar should behave in conversations.

`startScript` `string or null`
Optional opening message that the avatar will say when a session starts. Set to null to clear.

One of the following shapes: `string` <= 2000 characters Optional opening message that the avatar will say when a session starts. Set to null to clear.

`null` Optional opening message that the avatar will say when a session starts. Set to null to clear.

`voice` `RunwayLivePresetVoice (object) or CustomVoice (object)`
The voice configuration for the avatar.

One of the following shapes:`RunwayLivePresetVoice` `object` A preset voice from the Runway API.

`type` *(required)* `string`
This field must be set to the exact value `runway-live-preset`.

`presetId` *(required)* `string`
Accepted values:"victoria", "vincent", "clara", "drew", "skye", "max", "morgan", "felix", "mia", "marcus", "summer", "ruby", "aurora", "jasper", "leo", "adrian", "nina", "emma", "blake", "david", "maya", "nathan", "sam", "georgia", "petra", "adam", "zach", "violet", "roman", "luna" The ID of a preset voice. Available voices: `victoria` (Victoria), `vincent` (Vincent), `clara` (Clara), `drew` (Drew), `skye` (Skye), `max` (Max), `morgan` (Morgan), `felix` (Felix), `mia` (Mia), `marcus` (Marcus), `summer` (Summer), `ruby` (Ruby), `aurora` (Aurora), `jasper` (Jasper), `leo` (Leo), `adrian` (Adrian), `nina` (Nina), `emma` (Emma), `blake` (Blake), `david` (David), `maya` (Maya), `nathan` (Nathan), `sam` (Sam), `georgia` (Georgia), `petra` (Petra), `adam` (Adam), `zach` (Zach), `violet` (Violet), `roman` (Roman), `luna` (Luna).

`CustomVoice` `object` A custom voice created via the Voices API.

`type` *(required)* `string`
This field must be set to the exact value `custom`.

`id` *(required)* `string`
The ID of a custom voice created via the Voices API.

`documentIds` `strings` <= 50 items
List of knowledge document IDs to attach to this avatar. Replaces all current attachments. Documents provide additional context during conversations.

`imageProcessing` `string`
Default:"optimize"Accepted values:"optimize", "none" Controls image preprocessing. `optimize` improves the image for better avatar results. `none` uses the image as-is; quality not guaranteed.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

avatar = client.avatars.update(
id='550e8400-e29b-41d4-a716-446655440000',
name='Updated Avatar Name',
)
print(avatar)
```

`AvatarProcessing`, `AvatarReady`, `AvatarFailed````json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08","name": "string","personality": "string","startScript": "string","voice": {"type": "runway-live-preset","presetId": "victoria","name": "string","description": "string"},"referenceImageUri": "string","processedImageUri": "string","documentIds": ["497f6eca-6276-4993-bfeb-53cbbbba6f08"],"createdAt": "2019-08-24T14:15:22Z","updatedAt": "2019-08-24T14:15:22Z","status": "AvatarProcessing"}
```

## Delete avatar

`DELETE /v1/avatars/{id}`

Delete an avatar.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Path parameters

`id` *(required)* `string`

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

client.avatars.delete(id='550e8400-e29b-41d4-a716-446655440000')
```

## Knowledge

## Create document

`POST /v1/documents`

Create a new knowledge document. Documents can be attached to avatars to provide additional context during conversations.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`name` *(required)* `string` [ 1 .. 255 ] characters
A descriptive name for the document.

`content` *(required)* `string` [ 1 .. 200000 ] characters
The markdown or plain text content of the document.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

document = client.documents.create(
name='Product FAQ',
content='# Product FAQ## What is your return policy?\n...',
)
print(document)
```

```json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08","name": "string","type": "text","usedBy": [{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08","name": "string","imageUrl": "http://example.com"}],"content": "string","createdAt": "2019-08-24T14:15:22Z","updatedAt": "2019-08-24T14:15:22Z"}
```

## List documents

`GET /v1/documents`

List knowledge documents for the authenticated user with cursor-based pagination.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Query parameters

`limit` *(required)* `integer` [ 1 .. 100 ]
Default:50 The maximum number of items to return per page.

`cursor` `string` [ 1 .. 1000 ] characters
Cursor from a previous response for fetching the next page of results.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

for document in client.documents.list():
print(document)
```

```json
{"data": [{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08","name": "string","type": "text","usedBy": [{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08","name": "string","imageUrl": "http://example.com"}],"createdAt": "2019-08-24T14:15:22Z","updatedAt": "2019-08-24T14:15:22Z"}],"hasMore": true,"nextCursor": "string"}
```

## Get document

`GET /v1/documents/{id}`

Get details of a specific knowledge document.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Path parameters

`id` *(required)* `string`
The document ID.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

document = client.documents.retrieve(
id='550e8400-e29b-41d4-a716-446655440000'
)
print(document)
```

```json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08","name": "string","type": "text","usedBy": [{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08","name": "string","imageUrl": "http://example.com"}],"content": "string","createdAt": "2019-08-24T14:15:22Z","updatedAt": "2019-08-24T14:15:22Z"}
```

## Update document

`PATCH /v1/documents/{id}`

Update a knowledge document. At least one of `name` or `content` must be provided.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Path parameters

`id` *(required)* `string`
The document ID.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`name` `string` [ 1 .. 255 ] characters
A new name for the document.

`content` `string` [ 1 .. 200000 ] characters
New markdown or plain text content for the document.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

client.documents.update(
id='550e8400-e29b-41d4-a716-446655440000',
name='Updated Product FAQ',
)
```

## Delete document

`DELETE /v1/documents/{id}`

Delete a knowledge document. This also removes it from all avatars it was attached to.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Path parameters

`id` *(required)* `string`
The document ID.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

client.documents.delete(id='550e8400-e29b-41d4-a716-446655440000')
```

## Realtime Sessions

## Create realtime session

`POST /v1/realtime_sessions`

Create a new realtime session with the specified model configuration.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`model` *(required)* `string`
The realtime session model type.

This field must be set to the exact value `gwm1_avatars`.

`avatar` *(required)* `RunwayPresetAvatar (object) or CustomAvatar (object)`
The avatar configuration for the session.

One of the following shapes:`RunwayPresetAvatar` `object` A preset avatar from Runway.

`type` *(required)* `string`
This field must be set to the exact value `runway-preset`.

`presetId` *(required)* `string`
Accepted values:"game-character", "music-superstar", "game-character-man", "cat-character", "influencer", "tennis-coach", "human-resource", "fashion-designer", "cooking-teacher" ID of a preset avatar.

`CustomAvatar` `object` A user-created avatar.

`type` *(required)* `string`
This field must be set to the exact value `custom`.

`avatarId` *(required)* `string`
ID of a user-created avatar.

`maxDuration` `integer` [ 10 .. 300 ]
Default:300 Maximum session duration in seconds.

`personality` `string` [ 1 .. 2000 ] characters
Override the avatar personality for this session. If not provided, uses the avatar default.

`startScript` `string` [ 1 .. 2000 ] characters
Override the avatar start script for this session. If not provided, uses the avatar default.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

session = client.realtime_sessions.create(
model='gwm1_avatars',
avatar={
'type': 'custom',
'avatar_id': '550e8400-e29b-41d4-a716-446655440000',
},
)
print(session.id)
```

```json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08"}
```

## Get realtime session

`GET /v1/realtime_sessions/{id}`

Get the status of a realtime session.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Path parameters

`id` *(required)* `string`
The realtime session ID.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

session = client.realtime_sessions.retrieve(
id='550e8400-e29b-41d4-a716-446655440000'
)
print(session.status)
```

`SessionNotReady`, `SessionReady`, `SessionRunning`, `SessionCompleted`, `SessionFailed`, `SessionCancelled````json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08","createdAt": "2019-08-24T14:15:22Z","status": "SessionNotReady","queued": true}
```

## Cancel realtime session

`DELETE /v1/realtime_sessions/{id}`

Cancel an active realtime session.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Path parameters

`id` *(required)* `string`
The realtime session ID.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

client.realtime_sessions.delete(
id='550e8400-e29b-41d4-a716-446655440000'
)
```

## Organization

## Get organization information

`GET /v1/organization`

Get usage tier and credit balance information about the organization associated with the API key used to make the request.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

details = client.organization.retrieve()
print(details.creditBalance)
```

```json
{"tier": {"maxMonthlyCreditSpend": 9007199254740991,"models": {"property1": {"maxConcurrentGenerations": 9007199254740991,"maxDailyGenerations": 9007199254740991},"property2": {"maxConcurrentGenerations": 9007199254740991,"maxDailyGenerations": 9007199254740991}}},"creditBalance": 9007199254740991,"usage": {"models": {"property1": {"dailyGenerations": 9007199254740991},"property2": {"dailyGenerations": 9007199254740991}}}}
```

## Query credit usage

`POST /v1/organization/usage`

Fetch credit usage data broken down by model and day for the organization associated with the API key used to make the request. Up to 90 days of data can be queried at a time.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`startDate` `string`
The start date of the usage data in ISO-8601 format (YYYY-MM-DD). If unspecified, it will default to 30 days before the current date. All dates are in UTC.

`beforeDate` `string`
The end date of the usage data in ISO-8601 format (YYYY-MM-DD), not inclusive. If unspecified, it will default to thirty days after the start date. Must be less than or equal to 90 days after the start date. All dates are in UTC.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

usage = client.organization.retrieve_usage()
print(usage)
```

```json
{"results": [{"date": "2019-08-24","usedCredits": [{"model": "gen4.5","amount": 9007199254740991}]}],"models": ["gen4.5"]}
```

## Voices

## List voices

`GET /v1/voices`

List custom voices for the authenticated organization with cursor-based pagination.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Query parameters

`limit` *(required)* `integer` [ 1 .. 100 ]
Default:50 The maximum number of items to return per page.

`cursor` `string` [ 1 .. 1000 ] characters
Cursor from a previous response for fetching the next page of results.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

for voice in client.voices.list():
print(voice)
```

```json
{"data": [{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08","name": "string","description": "string","createdAt": "2019-08-24T14:15:22Z","status": "PROCESSING"}],"hasMore": true,"nextCursor": "string"}
```

## Create a voice

`POST /v1/voices`

Create a custom voice from a text description.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`name` *(required)* `string` [ 1 .. 100 ] characters
A name for the voice.

`from` *(required)* `object`
The source configuration for creating the voice.

`type` *(required)* `string`
This field must be set to the exact value `text`.

`prompt` *(required)* `string` [ 20 .. 1000 ] characters
A text description of the desired voice characteristics. Must be at least 20 characters.

`model` *(required)* `string`
Accepted values:"eleven_multilingual_ttv_v2", "eleven_ttv_v3" The voice design model to use.

`description` `string or null`
An optional description of the voice.

One of the following shapes: `string` [ 1 .. 512 ] characters An optional description of the voice.

`null` An optional description of the voice.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

voice = client.voices.create(
name='My Custom Voice',
from_={
'type': 'text',
'prompt': 'A warm, friendly voice with a slight British accent',
'model': 'eleven_multilingual_ttv_v2',
},
)
print(voice.id)
```

```json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08"}
```

## Get a voice

`GET /v1/voices/{id}`

Get details about a specific custom voice.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Path parameters

`id` *(required)* `string`
The ID of the voice to retrieve.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

voice = client.voices.retrieve(id='550e8400-e29b-41d4-a716-446655440000')
print(voice)
```

`VoiceProcessing`, `VoiceReady`, `VoiceFailed````json
{"id": "497f6eca-6276-4993-bfeb-53cbbbba6f08","name": "string","description": "string","createdAt": "2019-08-24T14:15:22Z","status": "VoiceProcessing"}
```

## Delete a voice

`DELETE /v1/voices/{id}`

Delete a custom voice.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Path parameters

`id` *(required)* `string`
The ID of the voice to delete.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

client.voices.delete(id='550e8400-e29b-41d4-a716-446655440000')
```

## Preview a voice

`POST /v1/voices/preview`

Generate a short audio preview of a voice from a text description. Use this to audition a voice before creating it.

### Authentication

`Authorization`
Use the HTTP `Authorization` header with the `Bearer` scheme along with an API key.

### Headers

`X-Runway-Version` *(required)* `string`
The version of the RunwayML API being used. You can read more about versioning [here](/api-details/versioning).

This field must be set to the exact value `2024-11-06`.

### Request body

`prompt` *(required)* `string` [ 20 .. 1000 ] characters
A text description of the desired voice characteristics. Must be at least 20 characters.

`model` *(required)* `string`
Accepted values:"eleven_multilingual_ttv_v2", "eleven_ttv_v3" The voice design model to use.

### Responses

```
# pip install runwayml
from runwayml import RunwayML

# The env var RUNWAYML_API_SECRET is expected to contain your API key.
client = RunwayML()

preview = client.voices.preview(
prompt='A warm, friendly voice with a slight British accent',
model='eleven_multilingual_ttv_v2',
)
print(preview.url, preview.duration_secs)
```

```json
{"url": "http://example.com","durationSecs": 0}
```
Type-specific requirements
Images
For fields that accept images, the asset must use one of the following encodings, along with the corresponding Content-Type header:

Codec	Content-Type header
JPEG	image/jpg or image/jpeg
PNG	image/png
WebP	image/webp
GIF images are not supported.

Videos
For fields that accept videos, the asset must use one of the following codecs, along with the corresponding Content-Type header:

Container format	Usual file extension	Expected content type	Supported codecs
MP4	.mp4	video/mp4	H.264, H.265/HEVC, AV1
QuickTime	.mov	video/quicktime	H.264, H.265/HEVC, Apple ProRes (422 Proxy, 422 LT, 422, 422 HQ, 4444, 4444 XQ)
Matroska	.mkv	video/x-matroska	H.264, H.265/HEVC, VP8, VP9, AV1
WebM	.webm	video/webm	VP8, VP9, AV1
3GPP	.3gp	video/3gpp	H.264
Ogg	.ogv	video/ogg	Theora
The following formats are supported but discouraged due to quality, performance, industry support, and file size:

Container format	Usual file extension	Expected content type	Supported codecs
QuickTime	.mov	video/quicktime	MJPEG
Matroska	.mkv	video/x-matroska	MPEG2 (H.262)
AVI	.avi	video/x-msvideo	H.264, MJPEG, MSMPEG4v3
Flash Video	.flv	video/x-flv	FLV1, H.264
MPEG	.mpg, .mpeg	video/mpeg	MPEG2 (H.262)
Note that file extension is not considered by the API. Use this value for reference only.

H.264 / AVC - Most widely supported modern codec
H.265 / HEVC - High efficiency successor to H.264
AV1 - Royalty-free, modern codec
VP8 / VP9 - Google’s codecs, primarily for WebM
Apple ProRes - Professional editing codec (422 Proxy, 422 LT, 422, 422 HQ, 4444, 4444 XQ)
MPEG2 (H.262) - Legacy codec for DVDs and broadcasts (discouraged)
MJPEG - Motion JPEG, frame-by-frame compression (discouraged)
Theora - Open codec for Ogg containers
FLV1 - Legacy Flash Video codec (discouraged)
MSMPEG4v3 - Legacy Microsoft codec (discouraged)
Audio
For fields that accept audio, the asset must use one of the following codecs, along with the corresponding Content-Type header:

Container format	Usual file extension	Content type	Supported codecs
MP3	.mp3	audio/mpeg, audio/mp3	MP3 (MPEG-1/2 Layer 3)
WAV	.wav	audio/wav, audio/wave, audio/x-wav	PCM (uncompressed)
FLAC	.flac	audio/flac, audio/x-flac	FLAC (lossless)
M4A	.m4a	audio/mp4, audio/x-m4a	AAC, ALAC
AAC	.aac	audio/aac, audio/x-aac	AAC (raw)
MP3 (MPEG-1/2 Layer 3) - Universal compatibility, lossy compression
AAC (Advanced Audio Coding) - Modern lossy codec, better quality than MP3 at same bitrate
FLAC (Free Lossless Audio Codec) - Lossless compression, popular for archival
PCM (Pulse Code Modulation) - Uncompressed audio, typically in WAV containers
ALAC (Apple Lossless Audio Codec) - Apple’s lossless codec, typically in M4A containers
Aspect ratios and auto-cropping of inputs
Video inputs
When using video models, be aware of the supported ratio parameters, which configures the dimensions of the output files.

Examples:

Gen-4.5 Text-to-Video supports Landscape 1280:720 and Portrait 720:1280 outputs only.
Gen-4.5 Image-to-Video supports Landscape 1280:720 1584:672 1104:832, Portrait 720:1280 832:1104 672:1584 and Square 960:960 outputs.
Ephemeral uploads
When providing files as inputs, there are size limits for assets provided by URL or data URI. URLs need to be downloaded and data URIs must be processed as part of the request body: both consume resources at the time a generation is started. To avoid these limits, you can upload ephemeral files to the Runway API using the uploads API.

Uploading files
You can upload a file to Runway by using our SDKs.

Node
Python
You can pass the following types to create_ephemeral:

pathlib.Path object or an object that implements os.PathLike
An IOBase object (e.g., BytesIO) with a name property containing the filename
from pathlib import Path

from runwayml import RunwayML
client = RunwayML()

my_file = Path('./path/to/file.mp4')
response = client.uploads.create_ephemeral(file=my_file)
print(response.uri)  # runway://...

If you do not have a Path or IOBase with a name, you can pass a two-tuple in the form (filename, content) where filename is the name of the file and content is one of:

A file-like object (e.g., the output of open())
bytes
from runwayml import RunwayML
client = RunwayML()

with open('./path/to/file.mp4') as my_file:
  response = client.uploads.create_ephemeral(
    file=('file.mp4', my_file),
  )
print(response.uri)  # runway://...

The resulting runway:// URI can be used anywhere that a URL or data URI can be used in the API.

Considerations
runway:// URIs are only valid for 24 hours.
The maximum uploadable file is 200MB. The minimum uploadable file is 512 bytes.
You must have purchased credits to use this feature.
There is a rate limit on the upload of ephemeral files.
Ephemeral uploads may be used multiple times, which can conserve bandwidth. If you intend to use a file multiple times, consider using ephemeral uploads. Be aware, though, that the URI will expire 24 hours after creation and the file must be re-uploaded.

Using ephemeral uploads without an SDK
Tip

See the API Reference for full details on using the /v1/uploads endpoint.

If you use our REST API directly, you can still use ephemeral uploads. By calling POST /v1/uploads with the following JSON body, you can start an upload:

{
  "filename": "filename.mp4",
  "type": "ephemeral"
}

filename: A string containing the filename of the file you are uploading. The file extension must be representative of the file’s contents.
type: Must be set to "ephemeral".
The server will respond with the following details:

{
  "uploadUrl": "https://...",
  "fields": { ... },
  "runwayUri": "runway://..."
}

The runwayUri value is the value that may be used when creating a new generation in the Runway API.

To upload the file to Runway’s servers, create a POST request to the URL at uploadUrl. Pass the fields in the dictionary fields as the multipart form-encoded POST body, and the contents of the file as as the file field.

Once the upload completes successfully, the runway:// URI is ready to use.

If the upload fails, do not retry. Instead, make a new request to /v1/uploads and start over. Be sure to follow our guidelines for handling errors to ensure your integration robustly handles different kinds of failure modes.

🎬 Runway Gen-4.5
Runway Gen-4.5 is the world’s top-rated video generation model, delivering unprecedented visual fidelity, cinematic realism, and precise creative control. It empowers creators and organizations to produce highly dynamic, controllable, and visually stunning video content at scale.

🚀 Overview
Two years ago, Gen-1 introduced the first publicly available video generation model, creating an entirely new category of creative tools. Since then, Runway has led the industry in advancing controllable and high-performance video models.

Gen-4.5 represents the next major leap in video generation — improving both:

Pre-training data efficiency
Post-training optimization techniques
Dynamic action generation
Temporal consistency
Precise controllability
With 1,247 Elo points, Gen-4.5 holds the #1 position in the Artificial Analysis Text-to-Video Benchmark (as of November 30, 2025).

Gen-4.5 maintains the speed and efficiency of Gen-4 while delivering breakthrough quality — all at comparable pricing across subscription plans.

🏆 Benchmark Leadership
#1 Ranked in Artificial Analysis Text-to-Video Leaderboard
1,247 Elo Score
Surpasses all competing video generation models
✨ Core Capabilities
🎯 Precise Prompt Adherence
Gen-4.5 achieves unprecedented physical accuracy and visual precision:

Realistic weight, momentum, and force in object motion
Accurate liquid dynamics
High-fidelity surface rendering
Coherent fine details (hair strands, fabric weave, textures) across motion
🎬 Complex Scene Generation
🧩 Intricate Multi-Element Scenes
Highly detailed environments rendered with precision and consistency.

🖼 Detailed Compositions
Precise placement and fluid motion for characters and objects.

⚙️ Physical Accuracy
Believable collisions, natural motion, and consistent physics.

🎭 Expressive Characters
Nuanced facial expressions, realistic gestures, and lifelike emotional depth.

🎨 Stylistic Control & Visual Consistency
Gen-4.5 supports a broad range of aesthetics while maintaining coherent visual language across frames.

📸 Photorealistic
Visuals indistinguishable from real-world footage.

🎨 Non-Photorealistic
Stylized and expressive animation unconstrained by realism.

🏡 Slice of Life
Authentic everyday environments with true-to-life detail.

🎥 Cinematic
Emotionally powerful visuals with striking depth and polish.

⚡ Performance & Deployment
🖥 High-Performance Infrastructure
Gen-4.5 was developed entirely on NVIDIA GPUs, spanning:

Initial research & development
Pre-training
Post-training
Inference
Inference runs on: - NVIDIA Hopper GPUs - NVIDIA Blackwell GPUs

Through deep collaboration with NVIDIA, Runway has optimized:

Training efficiency
Diffusion model optimization
Inference speed
All without compromising quality.

“This is an incredibly exciting time for video and world models.
We’re proud that Runway built their groundbreaking video and world model on NVIDIA GPUs…”
— Jensen Huang, President & CEO of NVIDIA

🏢 Early Access Enterprise Partners
Gen-4.5 is already in use across multiple industries:

Retail & E-commerce
Marketing & Advertising
Gaming
🧰 Supported Control Modes
Coming to Gen-4.5:

Image-to-Video
Keyframes
Video-to-Video
Additional advanced control modes
⚠️ Known Limitations
Despite significant advances, Gen-4.5 shares some limitations common to video generation systems:

🔄 Causal Reasoning
Effects may sometimes precede causes
(e.g., a door opening before the handle is pressed).

🫥 Object Permanence
Objects may disappear or reappear unexpectedly across frames.

🎯 Success Bias
Actions may succeed disproportionately
(e.g., a poorly aimed kick still scoring a goal).

These challenges are especially relevant to world model research, where accurate representation of action outcomes is critical. Ongoing research aims to address these limitations.

🌍 Built for the Future of Video
Gen-4.5 pushes the frontier of video generation by combining:

State-of-the-art realism
Fine-grained controllability
High-performance deployment
Broad accessibility
It makes world-class video generation available to creators and enterprises at every scale.

Model created 1 month ago

Learn how to run a model on Replicate from within your Python code. It could be an app, a notebook, an evaluation script, or anywhere else you want to use machine learning.

Tip

Check out an interactive notebook version of this tutorial on [Google Colab](https://colab.research.google.com/drive/1cLthjBaZ6qSRsI5izrgq95tNonRYnvxX).

[](#install-the-python-library)Install the Python library
---------------------------------------------------------

We maintain an [open-source Python client](https://github.com/replicate/replicate-python#readme) for the API. Install it with pip:

```plaintext
pip install replicate
```

[](#authenticate)Authenticate
-----------------------------

Generate an API token at [replicate.com/account/api-tokens](https://replicate.com/account/api-tokens), copy the token, then set it as an environment variable in your shell:

```shell
export REPLICATE_API_TOKEN=r8_....
```

[](#run-a-model)Run a model
---------------------------

You can run [any public model](https://replicate.com/explore) on Replicate from your Python code. Here’s an example that runs [black-forest-labs/flux-schnell](https://replicate.com/black-forest-labs/flux-schnell) to generate an image:

```python
import replicate
output = replicate.run(
  "black-forest-labs/flux-schnell",
  input={"prompt": "an iguana on the beach, pointillism"}
)
# Save the generated image
with open('output.png', 'wb') as f:
    f.write(output[0].read())
print(f"Image saved as output.png")
```

[](#using-local-files-as-inputs)Using local files as inputs
-----------------------------------------------------------

Some models take files as inputs. You can use a local file on your machine as input, or you can provide an HTTPS URL to a file on the public internet.

Here’s an example that uses a local file as input to the [LLaVA vision model](https://replicate.com/yorickvp/llava-13b), which takes an image and a text prompt as input and responds with text:

```python
import replicate
image = open("my_fridge.jpg", "rb")
output = replicate.run(
    "yorickvp/llava-13b:a0fdc44e4f2e1f20f2bb4e27846899953ac8e66c5886c5878fa1d6b73ce009e5",
    input={
        "image": image,
        "prompt": "Here's what's in my fridge. What can I make for dinner tonight?"
    }
)
print(output)
# You have a well-stocked refrigerator filled with various fruits, vegetables, and ...
```

[](#using-urls-as-inputs)Using URLs as inputs
---------------------------------------------

URLs are more efficient if your file is already in the cloud somewhere, or it is a large file.

Here’s an example that uses an HTTPS URL of an image on the internet as input to a model:

```python
image = "https://example.com/my_fridge.jpg"
output = replicate.run(
    "yorickvp/llava-13b:a0fdc44e4f2e1f20f2bb4e27846899953ac8e66c5886c5878fa1d6b73ce009e5",
    input={
        "image": image,
        "prompt": "Here's what's in my fridge. What can I make for dinner tonight?"
    }
)
print(output)
# You have a well-stocked refrigerator filled with various fruits, vegetables, and ...
```

[](#handling-output)Handling output
-----------------------------------

Some models stream output as the model is running. They will return an iterator, and you can iterate over that output.

Here’s an example that uses the [Claude 3.7 Sonnet model](https://replicate.com/anthropic/claude-3.7-sonnet) to generate text:

```python
iterator = replicate.run(
  "anthropic/claude-3.7-sonnet",
  input={"prompt": "Who was Dolly the sheep?"},
)
for text in iterator:
    print(text, end="")
# Dolly the sheep was the first mammal to be successfully cloned from an adult cell...
```

[](#handling-file-outputs)Handling file outputs
-----------------------------------------------

Some models generate files as output, such as images or audio. These are returned as `FileOutput` objects, which you can easily save or process:

```python
output = replicate.run(
    "black-forest-labs/flux-schnell",
    input={"prompt": "A majestic lion"}
)
# Save the generated image
with open('lion.png', 'wb') as f:
    f.write(output[0].read())
print("Image saved as lion.png")
# Handle multiple outputs
output = replicate.run(
    "black-forest-labs/flux-schnell",
    input={"prompt": "A majestic lion", "num_outputs": 2}
)
for idx, file_output in enumerate(output):
    with open(f'output_{idx}.png', 'wb') as f:
        f.write(file_output.read())

```

For more details on handling output files, see [Output Files](/docs/topics/predictions/output-files).

[](#next-steps)Next steps
-------------------------

Read the [full Python client documentation on GitHub.](https://github.com/replicate/replicate-python#readme)

Image to Video Prompting Guide

Runway: улучшенная работа с референсами и сохранением персонажей/лиц
-----------------------------------------------------------------

В этой кодовой базе сервис runway (bot/services/runway_service.py) был улучшен для
идеальной работы с референсами лиц / персонажей и для удобного сохранения
наборов референсов под именем персонажа. Ниже — краткое руководство по
новой логике, примеры использования и рекомендации по корректной работе.

Ключевые возможности
- Сохранение персонажа (имя + набор референсных изображений) в локальную
  JSON-базу data/runway_characters.json
- Использование сохранённого персонажа при запуске генерации через
  параметр character_id, приоритетно применяются сохранённые референсы
  (можно дополнять новыми изображениями/URL)
- Сохранённые референсы хранятся как runway-friendly строки: либо
  data:image/... (для байтов), либо обычные URL/ run-way URIs

API (примеры на Python)

Импорт и получение доступа к сервису (внутри проекта):

from bot.services.runway_service import runway_service

Сохранение персонажа (name, список URL и/или байтов):

char_id = runway_service.save_character(
    name="Anna",
    reference_image_urls=["https://example.com/anna1.png"],
    reference_images=[open("./local_ref.png","rb").read()],
    tags=["main", "promo"],
)
print("Saved character:", char_id)

Перечисление всех сохранённых персонажей:

for ch in runway_service.list_characters():
    print(ch["id"], ch["name"], len(ch.get("refs", [])))

Удаление персонажа:

ok = runway_service.delete_character(char_id)
print("deleted", ok)

Генерация видео с использованием сохранённого персонажа

# character_id — опциональный параметр. Если указан, сначала подставляются
# референсы, сохранённые для персонажа, затем дополняются явными
# reference_images/reference_image_urls из вызова.
res = await runway_service.generate_video(
    prompt="The camera slowly dollys in as the character looks surprised",
    duration=8,
    aspect_ratio="16:9",
    character_id=char_id,
)
print(res)

# Preserve identity by default
# The service now enables identity-preserving behavior by default. If you need
# to disable this (for stylistic reasons), pass preserve_identity=False:
#
# res = await runway_service.generate_video(..., preserve_identity=False)

Рекомендации и замечания
- Формат хранения: data/runway_characters.json — JSON-объект mapping id->meta.
  При необходимости вы можете перенести файл в более устойчивое хранилище.
- Байты изображений конвертируются в data URI (data:image/png;base64,...).
  Это удобно для SDK/Replicate, которые принимают data-URI в теле запроса.
- При вызове generate_video: если передан image_url явно, он становится
  стартовым кадром. Если image_url не передан, первым стартовым кадром
  станет первый элемент объединённого массива референсов (с учётом
  character_id).
- Сохранённые референсы используются в порядке сохранения. Если нужно
  контролировать приоритет — передавайте конкретные reference_image_urls
  в вызове generate_video (они будут добавлены после сохранённых, но если
  вы хотите, чтобы явно переданный URL был использован как стартовый кадр,
  передавайте его в image_url).
- Безопасность: файл с референсами содержит data URI, убедитесь, что
  доступ к нему ограничен в проде, если в референсах есть приватный контент.

Советы по качеству сохранения идентичности
- Перед сохранением персонажа добавляйте 3–4 изображения с разных ракурсов
  (фронт, полубок, профиль) — это значительно улучшит сохранение черт лица
  при генерации видео.
- Избегайте сильно обработанных изображений (фильтры, сильные искажения)
  — они ухудшают точность совпадения личности.
- Если нужно продолжительное сохранение / массовое использование, подумайте
  о миграции runway_characters.json в базу данных или объектное хранилище.

Где смотреть и как отладить
- Файл базы: data/runway_characters.json
- Логи: стандартный лог логгера runway_service (logger.getLogger(__name__))

Если нужно — могу добавить CLI-утилиту для управления персонажами
(list/save/delete) или интеграцию с бот-командами для сохранения через
Telegram-интерфейс.

Автоматическое сохранение персонажей (поведение по умолчанию)
-----------------------------------------------------------

Реализована автоматическая логика сохранения персонажей в боте для
максимального сохранения идентичности при генерации видео из фото
(Runway Gen-4.5). Когда вы создаёте видео из изображения и/или прикрепляете
референсные изображения в интерфейсе бота (новый UX), система теперь
автоматически:

- собирает стартовое изображение и загруженные референсы (URLs и/или байты)
- создаёт (или переиспользует) локальную запись персонажа в data/runway_characters.json
  (идентификатор строится детерминированно по имени/референсам)
- передаёт character_id в вызов Runway при отправке задачи — это даёт
  модели приоритетный набор референсов для лучшей консистентности лица/персонажа

Почему это полезно
- Пользователю не нужно вручную сохранять персонажей — бот автоматически
  агрегирует релевантные референсы и использует их при генерации.
- При повторных генерациях для одного пользователя персонажи будут
  переиспользоваться, что повышает вероятность сохранения черт лица.

Как отключить/удалить автоматически созданный персонаж
- Файл с персонажами: data/runway_characters.json
- Вы можете вручную удалить запись из этого файла или попросить меня
  добавить команды/CLI для управления персонажами (list/save/delete)

Примечание о приватности
- Автосохранение может включать data URI (base64) для загруженных байтов.
  Если у вас есть приватные референсы, рассмотрите возможность отключения
  автосохранения или хранения файла в защищённом окружении. Я могу добавить
  опцию "не сохранять автоматически" если это требуется.

Проблемы с передачей лиц (Troubleshooting)
-----------------------------------------

Если вы замечаете, что лица плохо передаются в получающемся видео (либо
изменяется внешность, глаза/нос некорректно расположены, или вообще нет
сходства), выполните следующие шаги для улучшения результата:

- Качество и ракурсы референсов:
  - Загрузите 3–4 фотографии лица с разными ракурсами: фронт, полубок, профиль
    и крупный план. Чем больше разнообразных, но чётких фото — тем лучше.
  - Используйте фотографии без сильных фильтров, искажений, сильного размытия
    или перекрывающих элементов (очки с отражением, маски и т.п.).

- Старотовое изображение (start image):
  - Для режима Фото→Видео (imgtxt) укажите стартовое изображение хорошего
    качества — оно станет основным ориентиром для композиции и лица.

- Как бот использует референсы (что мы сделали в коде):
  - Все загруженные референсы передаются Runway как элементы (elements)
    с полем frontal_image_url — это помогает модели понять фронтальное
    представление лица.
  - Если библиотека face_recognition доступна в окружении, бот попытается
    автоматически вырезать область с лицом (детекция) и передать её как
    frontal_image_url. Если face_recognition недоступна, бот делает центр‑кроп
    (центральный квадрат), что часто хорошо для обычных портретов.

- Установка необязательной зависимости (для улучшения детекции лиц):
  - Чтобы включить детекцию лиц на стороне бота, установите дополнительную

  pip install face_recognition

  - На некоторых системах установка dlib может требовать сборки и зависимостей
    (cmake, build-essential, libboost-all-dev и т.п.). Если установка проблемная,
    можно пропустить — бот всё ещё использует центр‑кроп.

  - Мы также добавили соответствующую заметку в requirements.txt под секцией
    "Optional (face detection for improved frontal crops)" с шагами установки
    системных пакетов и напоминанием, что это опционально.
    всё ещё использует центр‑кроп.

- Практические рекомендации по созданию запроса:
  - Укажите в промпте, что нужно сохранить идентичность персонажа: "preserve
    identity of the person in the reference images" (для Runway это может помочь).
  - Передавайте явные reference_image_urls/bytes — явные референсы повышают
    шанс получить похожее лицо.

- Если после улучшения входных фото проблема остаётся:
  - Попробуйте увеличить число референсов (но не более 4 ключевых для лица).
  - Сделайте отдельную генерацию теста: небольшая длительность + фокус на
    лице, чтобы проверить, как модель реагирует на ваши референсы.

Если хотите, могу:
- добавить в requirements.txt опциональную секцию с face_recognition,
- добавить CLI/команды для ручного выбора/подтверждения frontal crop перед отправкой,
- или включить режим ручного сохранения персонажа (чтобы вы могли подтверждать

Strict preserve mode (img1 / face_preservation)
----------------------------------------------

Мы добавили экспериментальную возможность "строгого" сохранения личности.
Когда вы хотите, чтобы стартовое изображение (img1) было гарантированно
использовано как образец лица, устанавливайте флаг strict_preserve_identity=True
в вызове generate_video. В этом режиме сервис:

- Добавляет в input.elements элемент для img1 с полем face_preservation: 100
  (сильный сигнал модели сохранить лицо как есть).
- Если frontal crop был получен из img1, он также помечается face_preservation=100.
- Опционально можно установить strict_preserve_identity=True, чтобы выставить
  frontal_image_url для каждого переданного референса (экстремальный режим).

Пример использования:

res = await runway_service.generate_video(
    prompt="мужчина танцует",
    image_url="https://.../img1.png",
    reference_image_urls=["https://.../img2.png"],
    preserve_identity=True,                # по умолчанию
    strict_preserve_identity=False,        # включите для жёсткой стратегии
)

Если вы хотите, чтобы img1 всегда был сохранён как лицо 100% без дополнительных
изменений, установите strict_preserve_identity=True при тестировании.

Отладка и тестирование
- Проведите тест с тем же payload, который раньше давал плохой результат, но
  теперь укажите strict_preserve_identity=True. Отправьте лог input_data или
  webhook payload если результат снова неправильный — я проанализирую конкретный
  payload и подскажу дальнейшие шаги.
  какие изображения попадут в frontal_image_url).


Table of Contents
Core prompt elements
Prompt structure & organization
Advanced techniques
FAQ
Introduction
Image to Video models transform images into videos with a text prompt. When using this generative mode, your image defines composition, subject matter, lighting, and style that guide the video. 

Your prompt's role is to describe what should happen — the motion, camera work, and temporal progression you want to see using clear, direct language.

Runway_The_camera_executes_an_aggressive,_012026.gif
Prompt: The camera executes an aggressive, sweeping horizontal arc around the subject, followed by an extremely rapid, aggressive crash zoom that concludes with a sharp focus on the subject's eyes.
This guide builds on knowledge outlined in our Introduction to Prompting guide by introducing concepts specific to Image to Video, and is currently optimized for the newest Gen-4.5 model. 

After completing this guide, you will understand how to create Image to Video prompts that produce videos matching your creative intent.

 

Related articles
Introduction to Prompting
Creating with Gen-4.5
Camera Terms, Prompts, & Examples
Text to Video Prompting Guide
 

Core prompt elements
Text prompt
Effective image to video prompts focus almost exclusively on motion. Rather than describing elements present in the image, use your prompt to describe the motion of the scene.

 

Motion components

Subject action
Environmental motion
Camera motion
Motion style & timing
Direction & speed
 

To control individual elements from your image, refer to characters and objects with general language to isolate them and define motion.

 

Do I need to include every component in my prompt?
Are there situations where I should describe visual components?
 

Image prompt
Your input image acts as the first frame and provides the model with the composition, subject matter, lighting, and style information for the video. 

For best results, ensure that the input image is high quality and free of visual artifacts. Visual artifacts, such as blurry hands or faces, may be intensified once your image is transformed into a video.

 

Prompt structure & organization
You don’t need to follow a strict formula to generate great results. Structure and order are far less important than clearly conveying an idea and reducing ambiguity.

However, establishing an organization method can assist with effectively conveying ideas and make future iteration easier. We recommend trying this structure if you’re new to generative media:

The camera [motion description] as the subject [action]. [Additional descriptions]
 

Click to view different examples of prompts following a similar structure
Text prompt	Image prompt	Result
The camera slowly pushes in as the person scales the giant soda. 	
30fbe3c4-a55d-4b09-b5ce-3fee4cbc9a48.png
Gen-4_5 the person scales the giant soda 2512124562.gif
Handheld camera: The man stands still as the crowd moves around him. He starts yelling as the camera slowly zooms out. Natural camera shake.	
man.jpg
Adobe Express - Gen-4_5 hand held camera the man stands still as the crowd moves around her, he starting yelling as the camera slowly zooms outHandheld documentary film style Natural camera shake Raw indie aestheti.gif
Whip pan to painting of a fox. Whip pan back to the woman with a curious expression. Whip pan back to the fox painting, the fox is moving.	
d3624c8c-fa5a-4c0f-88e9-d8f1061fc20c.png
Gen-4_5 1 whip pan to painting of a fox2 whip pan back to the woman with a curious expression3 whip pan back to the fox painting, the fox is moving 3855905079 (1).gif
For more prompt examples and their outputs, please see our Camera Terms, Prompts, & Examples.

 

Advanced techniques
Sequential prompting
Sequential prompting provides an order of events for temporal control. This can be done through natural language, or by providing rough timestamps for an action to occur:

Natural language: X occurs, then Y occurs. Finally, Z occurs.
Timestamps: [00:01] X occurs. [00:03] Y occurs. [00:04] Z occurs.
For best results, consider if the requested sequences make sense with the selected duration. You may opt for a higher durations for more complex sequences.

 

Creating longer sequences
Create longer sequences by extracting the last frame of a completed generation and using that as the image input for a new video.

To extract the last frame:

Move the playback scrubber to the very end of the completed video
Select Use from beneath the video
Select Use current frame
This will load in the selected frame into the current model. Once the generation completes, you can combine both clips in a video editor to adjust timing and remove the shared frame.

 

FAQ
Why am I having challenges receiving the desired motion with a certain image?
Input images can contain implied motion through elements like motion blur, mid-action elements and poses, or directional lines. Prompting for motion that contradicts these visual cues may require more iteration to achieve your desired result.

If you're not getting the motion you want after several iterations, check your input image for implied motion cues and consider using Text/Image to Image to remove or minimize cues before generating.

 	Input image	Prompt	Result
Prevalent motion cues: motion blur, dust clouds	
add_motion_blur_and_dust_clouds_behind_the_back_wheels__keep_the_composition_the_same_2.png
The car is parked and completely motionless. The camera performs an aggressive, sweeping horizontal arc around the parked car.	
Gen-4_5 The car is parked and completely motionless The camera performs an aggressive, sweeping horizontal arc around the parked car 324793778.gif
Minimized motion cues	
orange_truck_on_white_sand_dune__professional_photography__stylized__staged__car_photography_3.png
Gen-4_5 The car is completely motionless The camera performs an aggressive, sweeping horizontal arc around the parked car 2166293514.gif
In the above example, prompting for a motionless, parked car was contradictory to the prominent dust clouds and motion blur that act as motion cues. Removing the dust clouds and motion blur from the image provided the desired results with the same prompt.

Why did I receive an unwanted cut in my video?
Receiving unwanted cuts in your video may indicate that your image and prompt combination would benefit from a higher duration.

First, try increasing the duration to iterate for a seamless shot. If cuts continue to occur, check your prompt for phrasing that might indicate a cut and consider adding a prompt component like Continuous, seamless shot to your input.

How do I minimize camera motion for my shot?
Video models are designed to produce motion, so ensuring that you describe what motion should occur within the frame is important to receiving shots with less motion.

However, this alone may not result in a perfectly still shot. You can try adding prompt elements like the examples below to further reinforce minimal motion:

The locked-off camera remains perfectly still.
The camera must start and end on the exact same frame to create a perfect loop.
Minimal subject motion only.
Using these methods to reduce camera motion and then stablizing the shot in a video editor can help achieve the desired effect. Alternatively, consider using the Animate Frames app using the same image for both inputs for even more control
Image to Video Prompting Guide

Table of Contents
Core prompt elements
Prompt structure & organization
Advanced techniques
FAQ
Introduction
Image to Video models transform images into videos with a text prompt. When using this generative mode, your image defines composition, subject matter, lighting, and style that guide the video. 

Your prompt's role is to describe what should happen — the motion, camera work, and temporal progression you want to see using clear, direct language.

Runway_The_camera_executes_an_aggressive,_012026.gif
Prompt: The camera executes an aggressive, sweeping horizontal arc around the subject, followed by an extremely rapid, aggressive crash zoom that concludes with a sharp focus on the subject's eyes.
This guide builds on knowledge outlined in our Introduction to Prompting guide by introducing concepts specific to Image to Video, and is currently optimized for the newest Gen-4.5 model. 

After completing this guide, you will understand how to create Image to Video prompts that produce videos matching your creative intent.

 

Related articles
Introduction to Prompting
Creating with Gen-4.5
Camera Terms, Prompts, & Examples
Text to Video Prompting Guide
 

Core prompt elements
Text prompt
Effective image to video prompts focus almost exclusively on motion. Rather than describing elements present in the image, use your prompt to describe the motion of the scene.

 

Motion components

Subject action
Environmental motion
Camera motion
Motion style & timing
Direction & speed
 

To control individual elements from your image, refer to characters and objects with general language to isolate them and define motion.

 

Do I need to include every component in my prompt?
Are there situations where I should describe visual components?
 

Image prompt
Your input image acts as the first frame and provides the model with the composition, subject matter, lighting, and style information for the video. 

For best results, ensure that the input image is high quality and free of visual artifacts. Visual artifacts, such as blurry hands or faces, may be intensified once your image is transformed into a video.

 

Prompt structure & organization
You don’t need to follow a strict formula to generate great results. Structure and order are far less important than clearly conveying an idea and reducing ambiguity.

However, establishing an organization method can assist with effectively conveying ideas and make future iteration easier. We recommend trying this structure if you’re new to generative media:

The camera [motion description] as the subject [action]. [Additional descriptions]
 

Click to view different examples of prompts following a similar structure
Text prompt	Image prompt	Result
The camera slowly pushes in as the person scales the giant soda. 	
30fbe3c4-a55d-4b09-b5ce-3fee4cbc9a48.png
Gen-4_5 the person scales the giant soda 2512124562.gif
Handheld camera: The man stands still as the crowd moves around him. He starts yelling as the camera slowly zooms out. Natural camera shake.	
man.jpg
Adobe Express - Gen-4_5 hand held camera the man stands still as the crowd moves around her, he starting yelling as the camera slowly zooms outHandheld documentary film style Natural camera shake Raw indie aestheti.gif
Whip pan to painting of a fox. Whip pan back to the woman with a curious expression. Whip pan back to the fox painting, the fox is moving.	
d3624c8c-fa5a-4c0f-88e9-d8f1061fc20c.png
Gen-4_5 1 whip pan to painting of a fox2 whip pan back to the woman with a curious expression3 whip pan back to the fox painting, the fox is moving 3855905079 (1).gif
For more prompt examples and their outputs, please see our Camera Terms, Prompts, & Examples.

 

Advanced techniques
Sequential prompting
Sequential prompting provides an order of events for temporal control. This can be done through natural language, or by providing rough timestamps for an action to occur:

Natural language: X occurs, then Y occurs. Finally, Z occurs.
Timestamps: [00:01] X occurs. [00:03] Y occurs. [00:04] Z occurs.
For best results, consider if the requested sequences make sense with the selected duration. You may opt for a higher durations for more complex sequences.

 

Creating longer sequences
Create longer sequences by extracting the last frame of a completed generation and using that as the image input for a new video.

To extract the last frame:

Move the playback scrubber to the very end of the completed video
Select Use from beneath the video
Select Use current frame
This will load in the selected frame into the current model. Once the generation completes, you can combine both clips in a video editor to adjust timing and remove the shared frame.

 

FAQ
Why am I having challenges receiving the desired motion with a certain image?
Input images can contain implied motion through elements like motion blur, mid-action elements and poses, or directional lines. Prompting for motion that contradicts these visual cues may require more iteration to achieve your desired result.

If you're not getting the motion you want after several iterations, check your input image for implied motion cues and consider using Text/Image to Image to remove or minimize cues before generating.

 	Input image	Prompt	Result
Prevalent motion cues: motion blur, dust clouds	
add_motion_blur_and_dust_clouds_behind_the_back_wheels__keep_the_composition_the_same_2.png
The car is parked and completely motionless. The camera performs an aggressive, sweeping horizontal arc around the parked car.	
Gen-4_5 The car is parked and completely motionless The camera performs an aggressive, sweeping horizontal arc around the parked car 324793778.gif
Minimized motion cues	
orange_truck_on_white_sand_dune__professional_photography__stylized__staged__car_photography_3.png
Gen-4_5 The car is completely motionless The camera performs an aggressive, sweeping horizontal arc around the parked car 2166293514.gif
In the above example, prompting for a motionless, parked car was contradictory to the prominent dust clouds and motion blur that act as motion cues. Removing the dust clouds and motion blur from the image provided the desired results with the same prompt.

Why did I receive an unwanted cut in my video?
Receiving unwanted cuts in your video may indicate that your image and prompt combination would benefit from a higher duration.

First, try increasing the duration to iterate for a seamless shot. If cuts continue to occur, check your prompt for phrasing that might indicate a cut and consider adding a prompt component like Continuous, seamless shot to your input.

How do I minimize camera motion for my shot?
Video models are designed to produce motion, so ensuring that you describe what motion should occur within the frame is important to receiving shots with less motion.

However, this alone may not result in a perfectly still shot. You can try adding prompt elements like the examples below to further reinforce minimal motion:

The locked-off camera remains perfectly still.
The camera must start and end on the exact same frame to create a perfect loop.
Minimal subject motion only.
Using these methods to reduce camera motion and then stablizing the shot in a video editor can help achieve the desired effect. Alternatively, consider using the Animate Frames app using the same image for both inputs for even more control
Introduction
Writing prompts for generative image and video models is a new skill that builds on communication abilities you already have. Just like giving creative direction to a colleague, prompting requires you to articulate your vision clearly.

The key difference is that generative models interpret your words more literally and lack the shared context that a colleague might have. If you prompt a beautiful landscape, the model doesn't know whether you envision mountains at sunset or a tropical beach at noon:

Prompt: A beautiful landscape
Gen-4_5 a beautiful landscape 620499604.mp4.gif
Gen-4_5 a beautiful environment 3302791039.mp4.gif
Both interpretations are technically correct, but may not match your vision. 

This guide explains how to write effective prompts by starting simple and adding detail strategically, using positive language, and embracing iteration as part of the creative process.
 

Related links
Camera Terms, Prompts, & Examples 
Text to Video Prompting Guide
Image to Video Prompting Guide
Creating with Gen-4.5
 

 

Iteration is part of the process
Before diving into techniques, understand that getting the perfect result may not happen on the first try. Creative work (whether you're writing, designing, or filming) involves drafting, collaborating, and refining. The same is normal and expected when working with generative media.

Think of prompting as a conversation with the model: You make a request, review the response, then clarify or expand your request based on what you see. Each generation teaches you something new about how the model interprets your words.

Iteration 1	Iteration 2	Iteration 3
A serene pond with koi fish	High angle looking down at a serene pond with koi fish	High angle looking down at a serene pond. A koi fish emerges and breaches the surface, sending gentle ripples through the surrounding lily pads.
Gen-4_5 A serene pond with koi fish 3704565279.mp4.gif
Gen-4_5 Bird's eye view looking directly down at a serene pond with koi fish 1168355221.mp4.gif
Gen-4_5 Bird's eye view looking directly down at a serene pond A koi fish emerges and breaches the surface, sending gentle ripples through the surrounding lily pads 1487425890.mp4.gif
This iterative approach is often intentionally leveraged in workflows by seasoned creators, as it lets you refine your vision as you simultaneously explore possibilities you hadn't imagined.

 

 

Prompting strategies
There are two main approaches when writing an initial prompt. Each has distinct advantages depending on your workflow:

Starting simple lets you add one element at a time and see what each change does. 
Starting detailed can reduce the total steps in your iteration process, getting you closer to a desired result faster. 
True or False? Detailed prompts are always better than simple prompts.
False. Simple and detailed prompts are both valid and effective approaches to prompting.

Seasoned creators freely switch between both strategies as need for exploration (simple) or refining results (detailed).

Strategy	Pros	Cons
Simple	
Faster to write and iterate
Gives model creative freedom
Better for exploration
May require more iteration
Inconsistent outputs across multiple generations
Detailed	
Reduces ambiguity
Consistency across generations
Better for projects with defined requirements
Takes more time to write
Limits model creative freedom
More challenging to troubleshoot
 

Click each strategy type to learn more and review examples:

Simple
You don't always need elaborate prompts. Simple instructions like "a cat sitting on a windowsill" or "a person walking through a city street" can produce excellent results. These prompts give the model creative freedom to interpret details like lighting, camera movement, composition, and style.

Think of simple prompts as sketches. They're fast, flexible, and perfect for early creative exploration. When a basic prompt doesn't quite work, you can always add more details to refine the result.

When starting simple, you're building on a foundation rather than troubleshooting a paragraph of details.

Detailed
Detailed prompts help when you need results that match particular requirements, like a specific mood, setting, or visual style. Starting with more detail will reduce the total number of iterations needed to work towards your final result.

When adding detail to a prompt, use these fundamental questions to reduce ambiguity:

Who or what is the subject?	Be specific about the main focus. "A person" could be anyone, but "a serious woman in her 30s wearing business attire" creates a clearer picture.
What is happening?	Describe the action or state. "Standing" and "running" create very different results, even with the same subject.
When does this take place?	Time of day affects lighting and mood. "Dawn" looks different from "midnight" or "midday."
Where is this happening?	Setting provides context. "In a forest" differs from "in a modern office" or "on a busy street."
How should it look?	This covers style, mood, and more technical aspects like camera motion. Consider the atmosphere (peaceful, energetic, mysterious) and visual approach (photographic, illustrated, cinematic).
The goal of detail is to remove ambiguity, not to control every pixel.

Extremely complex, multi-paragraph prompts reduce the room for creative freedom a model has, constraining it to operate within tightly defined parameters. This over-specification can paradoxically lead to unexpected or unnatural results, as the model struggles to honor every detail simultaneously.

 

 

Best practices
Following these best practices will improve your results:

Use positive phrasing
Models respond better to descriptions of what you want to happen rather than what you don't want to happen.

❌ not blurry
✅ sharp focus, high detail
Positive phrasing works because models are trained to create what you describe. When you say what not to include, the model still has to interpret that concept and may include it anyway.

Think of it like giving directions: "turn left at the library" is clearer than "don't turn right at the library."

Avoid ambiguous or conceptual language
Models interpret words literally and may not understand subjective or abstract terms the same way you do. Words like "beautiful," "professional," or "interesting" mean different things to different people.

❌ A beautiful sunset
✅ a sunset with vibrant orange and pink clouds over the ocean
Concrete descriptions work better because they give the model specific visual elements to create. Instead of saying something should look "modern," describe what modern means to you: clean lines, minimal decoration, neutral colors, or large windows.

Avoid conflicting instructions
When your prompt contains contradictory details, the model will try to honor all of them, often resulting in unclear or unexpected outcomes.

❌ dramatic shadows with soft, even lighting
✅ dramatic shadows with strong directional light
Review your prompt for elements that work against each other. Requesting both "peaceful, calm atmosphere" and "energetic, dynamic action" sends mixed signals. Asking for "vintage 1920s style" alongside "modern minimalist aesthetic" creates confusion about the overall look.

 

 

Troubleshooting results
When you're not getting the results you want after a few tries, step back and use these strategies to diagnose the issue and iterate your results.

Use Chat Mode to refine or rephrase your prompt
Simplify complex prompts
Reinforce missed elements through natural language
Know when and how to move on
 

FAQ
Do JSON prompts provide more accurate results than natural language prompts?
JSON prompts give the placebo effect of being more accurate. This is because JSON formatting forces creators to break down their visual concepts when they may not otherwise do so. Ultimately, JSON formatting is ignored by generative models– what matters is the detail provided within the prompt.

This can be accomplished more simplistically by asking the who, what, when, where, and how questions, which is what we recommend.


Python
Get started
Learn more
Schema
API reference

Create a prediction

predictions.create
Headers
Prefer
string
Leave the request open and wait for the model to finish generating output. Set to wait=n where n is a number of seconds between 1 and 60.

See sync mode for more information.

Show less
Cancel-After
string
The maximum time the prediction can run before it is automatically canceled. The lifetime is measured from when the prediction is created.

The duration can be specified as string with an optional unit suffix:

s for seconds (e.g., 30s, 90s)
m for minutes (e.g., 5m, 15m)
h for hours (e.g., 1h, 2h30m)
defaults to seconds if no unit suffix is provided (e.g. 30 is the same as 30s)
You can combine units for more precision (e.g., 1h30m45s).

The minimum allowed duration is 5 seconds.

Show less
Request body
input
object
Required
The model's input as a JSON object. The input schema depends on what model you are running. To see the available inputs, click the "API" tab on the model you are running or get the model version and look at its openapi_schema property. For example, stability-ai/sdxl takes prompt as an input.

Files should be passed as HTTP URLs or data URLs.

Use an HTTP URL when:

you have a large file > 256kb
you want to be able to use the file multiple times
you want your prediction metadata to be associable with your input files
Use a data URL when:

you have a small file <= 256kb
you don't want to upload and host the file somewhere
you don't need to use the file again (Replicate will not store it)
Show less
webhook
string
An HTTPS URL for receiving a webhook when the prediction has new output. The webhook will be a POST request where the request body is the same as the response body of the get prediction operation. If there are network problems, we will retry the webhook a few times, so make sure it can be safely called more than once. Replicate will not follow redirects when sending webhook requests to your service, so be sure to specify a URL that will resolve without redirecting.

Show less
webhook_events_filter
array
By default, we will send requests to your webhook URL whenever there are new outputs or the prediction has finished. You can change which events trigger webhook requests by specifying webhook_events_filter in the prediction request:

start: immediately on prediction start
output: each time a prediction generates an output (note that predictions can generate multiple outputs)
logs: each time log output is generated by a prediction
completed: when the prediction reaches a terminal state (succeeded/canceled/failed)
For example, if you only wanted requests to be sent at the start and end of the prediction, you would provide:

{
  "version": "5c7d5dc6dd8bf75c1acaa8565735e7986bc5b66206b55cca93cb72c9bf15ccaa",
  "input": {
    "text": "Alice"
  },
  "webhook": "https://example.com/my-webhook",
  "webhook_events_filter": ["start", "completed"]
}
Requests for event types output and logs will be sent at most once every 500ms. If you request start and completed webhooks, then they'll always be sent regardless of throttling.

Show less
Examples

Create
Create a prediction and get the output


Webhooks
Make a request
/predictions
import replicate

input = {
    "prompt": "A dense, verdant jungle world made up of small lego-like pieces. We see a rainbow chameleon running through the 3D world, the camera in and out of focus.",
    "duration": 10
}

output = replicate.run(
    "runwayml/gen-4.5",
    input=input
)

# To access the file URL:
print(output.url)
#=> "https://replicate.delivery/.../output.mp4"

# To write the file to disk:
with open("output.mp4", "wb") as file:
    file.write(output.read())
#=> output.mp4 written to disk

Copy

Get a prediction

predictions.get
Input parameters
prediction_id
string
Required
The ID of the prediction to get.
Examples

Get
Get the latest version of a prediction by id

Make a request
/predictions/{prediction_id}
import replicate

prediction = replicate.predictions.get(prediction_id)
print(prediction)
#=> Prediction(id="xyz...", status="successful", ... )
