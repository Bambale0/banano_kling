
полная Миграция moution control c piapi на replicate

Set the REPLICATE_API_TOKEN environment variable

export REPLICATE_API_TOKEN=r8_FjT**********************************

Visibility

Copy
Learn more about authentication

Install Replicate’s Python client library

pip install replicate

Copy
Learn more about setup
Run kwaivgi/kling-v2.6-motion-control using Replicate’s API. Check out the model's schema for an overview of inputs and outputs.

import replicate

input = {
    "mode": "pro",
    "image": "https://replicate.delivery/pbxt/OHMFuZ6vHcDd3sXoOnn5oGLBvZIq43HuAige2XeWLdBigLUs/santa.png",
    "video": "https://replicate.delivery/pbxt/OHMFv2w6blsLcBTvRSEujuJnNvRNXXEmyLlXIvpMSVzG8mhN/taichi.mp4"
}

output = replicate.run(
    "kwaivgi/kling-v2.6-motion-control",
    input=input
)

# To access the file URL:
print(output.url)
#=> "https://replicate.delivery/.../output.mp4"

# To write the file to disk:
with open("output.mp4", "wb") as file:
    file.write(output.read())
#=> output.mp4 written to disk
Authentication
Whenever you make an API request, you need to authenticate using a token. A token is like a password that uniquely identifies your account and grants you access.

The following examples all expect your Replicate access token to be available from the command line. Because tokens are secrets, they should not be in your code. They should instead be stored in environment variables. Replicate clients look for the REPLICATE_API_TOKEN environment variable and use it if available.

To set this up you can use:

export REPLICATE_API_TOKEN=r8_FjT**********************************

Visibility

Copy
Some application frameworks and tools also support a text file named .env which you can edit to include the same token:

REPLICATE_API_TOKEN=r8_FjT**********************************

Visibility

Copy
The Replicate API uses the Authorization HTTP header to authenticate requests. If you’re using a client library this is handled for you.

You can test that your access token is setup correctly by using our account.get endpoint:

What is cURL?
curl https://api.replicate.com/v1/account -H "Authorization: Bearer $REPLICATE_API_TOKEN"
# {"type":"user","username":"aron","name":"Aron Carroll","github_url":"https://github.com/aron"}

Copy
If it is working correctly you will see a JSON object returned containing some information about your account, otherwise ensure that your token is available:

echo "$REPLICATE_API_TOKEN"
# "r8_xyz"

Copy
Setup
First you’ll need to ensure you have a Python environment setup:

python -m venv .venv
source .venv/bin/activate

Copy
Then install the replicate Python library:

pip install replicate

Copy
In a main.py file, import replicate:

import replicate

Copy
This will use the REPLICATE_API_TOKEN API token you’ve set up in your environment for authorization.

Run the model
Use the replicate.run() method to run the model:

input = {
    "mode": "pro",
    "image": "https://replicate.delivery/pbxt/OHMFuZ6vHcDd3sXoOnn5oGLBvZIq43HuAige2XeWLdBigLUs/santa.png",
    "video": "https://replicate.delivery/pbxt/OHMFv2w6blsLcBTvRSEujuJnNvRNXXEmyLlXIvpMSVzG8mhN/taichi.mp4"
}

output = replicate.run(
    "kwaivgi/kling-v2.6-motion-control",
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
You can learn about pricing for this model on the model page.

The run() function returns the output directly, which you can then use or pass as the input to another model. If you want to access the full prediction object (not just the output), use the replicate.predictions.create() method instead. This will return a Prediction object that includes the prediction id, status, logs, etc.

File inputs
This model accepts files as input, e.g. image. You can provide a file as input using a URL, a local file on your computer, or a base64 encoded object:

Option 1: Hosted file
Use a URL as in the earlier example:

image = "https://replicate.delivery/pbxt/OHMFuZ6vHcDd3sXoOnn5oGLBvZIq43HuAige2XeWLdBigLUs/santa.png";

Copy
This is useful if you already have a file hosted somewhere on the internet.

Option 2: Local file
You can provide Replicate with a file object and the library will handle the upload for you:

image = open("./path/to/my/image.png", "rb");

Copy
Option 3: Data URI
Lastly, you can create a data URI consisting of the base64 encoded data for your file, but this is only recommended if the file is < 1mb:

import base64

with open("./path/to/my/image.png", 'rb') as file:
  data = base64.b64encode(file.read()).decode('utf-8')
  image = f"data:application/octet-stream;base64,{data}"

Copy
Then pass the file as part of the input:

input = {
    "mode": "pro",
    "image": image,
    "video": "https://replicate.delivery/pbxt/OHMFv2w6blsLcBTvRSEujuJnNvRNXXEmyLlXIvpMSVzG8mhN/taichi.mp4"
}

output = replicate.run(
    "kwaivgi/kling-v2.6-motion-control",
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
Prediction lifecycle
Running predictions and trainings can often take significant time to complete, beyond what is reasonable for an HTTP request/response.

When you run a model on Replicate, the prediction is created with a “starting” state, then instantly returned. This will then move to "processing" and eventual one of “successful”, "failed" or "canceled".

Starting
Running
Succeeded
Failed
Canceled
You can explore the prediction lifecycle by using the prediction.reload() method update the prediction to it's latest state.

Show example
Webhooks
Webhooks provide real-time updates about your prediction. Specify an endpoint when you create a prediction, and Replicate will send HTTP POST requests to that URL when the prediction is created, updated, and finished.

It is possible to provide a URL to the predictions.create() function that will be requested by Replicate when the prediction status changes. This is an alternative to polling.

To receive webhooks you’ll need a web server. The following example uses AIOHTTP, a basic webserver built on top of Python’s asyncio library, but this pattern will apply to most frameworks.

Show example
Then create the prediction passing in the webhook URL and specify which events you want to receive out of "start" , "output" ”logs” and "completed".

input = {
    "mode": "pro",
    "image": "https://replicate.delivery/pbxt/OHMFuZ6vHcDd3sXoOnn5oGLBvZIq43HuAige2XeWLdBigLUs/santa.png",
    "video": "https://replicate.delivery/pbxt/OHMFv2w6blsLcBTvRSEujuJnNvRNXXEmyLlXIvpMSVzG8mhN/taichi.mp4"
}

callback_url = "https://my.app/webhooks/replicate"
replicate.predictions.create(
  model="kwaivgi/kling-v2.6-motion-control",
  input=input,
  webhook=callback_url,
  webhook_events_filter=["completed"]
)

# The server will now handle the event and log:
#=> Prediction(id='z3wbih3bs64of7lmykbk7tsdf4', ...)

Copy
The replicate.run() method is not used here. Because we're using webhooks, and we don’t need to poll for updates.

From a security perspective it is also possible to verify that the webhook came from Replicate, check out our documentation on verifying webhooks for more information.

Access a prediction
You may wish to access the prediction object. In these cases it’s easier to use the replicate.predictions.create() function, which return the prediction object.

Though note that these functions will only return the created prediction, and it will not wait for that prediction to be completed before returning. Use replicate.predictions.get() to fetch the latest prediction.

import replicate

input = {
    "mode": "pro",
    "image": "https://replicate.delivery/pbxt/OHMFuZ6vHcDd3sXoOnn5oGLBvZIq43HuAige2XeWLdBigLUs/santa.png",
    "video": "https://replicate.delivery/pbxt/OHMFv2w6blsLcBTvRSEujuJnNvRNXXEmyLlXIvpMSVzG8mhN/taichi.mp4"
}

prediction = replicate.predictions.create(
  model="kwaivgi/kling-v2.6-motion-control",
  input=input
)
#=> Prediction(id='z3wbih3bs64of7lmykbk7tsdf4', ...)

Copy
Cancel a prediction
You may need to cancel a prediction. Perhaps the user has navigated away from the browser or canceled your application. To prevent unnecessary work and reduce runtime costs you can use prediction.cancel() method to call the predictions.cancel endpoint.

input = {
    "mode": "pro",
    "image": "https://replicate.delivery/pbxt/OHMFuZ6vHcDd3sXoOnn5oGLBvZIq43HuAige2XeWLdBigLUs/santa.png",
    "video": "https://replicate.delivery/pbxt/OHMFv2w6blsLcBTvRSEujuJnNvRNXXEmyLlXIvpMSVzG8mhN/taichi.mp4"
}

prediction = replicate.predictions.create(
  model="kwaivgi/kling-v2.6-motion-control",
  input=input
)

prediction.cancel()

Copy
Async Python methods
asyncio is a module built into Python's standard library for writing concurrent code using the async/await syntax.

Replicate's Python client has support for asyncio. Each of the methods has an async equivalent prefixed with async_<name>.

input = {
    "mode": "pro",
    "image": "https://replicate.delivery/pbxt/OHMFuZ6vHcDd3sXoOnn5oGLBvZIq43HuAige2XeWLdBigLUs/santa.png",
    "video": "https://replicate.delivery/pbxt/OHMFv2w6blsLcBTvRSEujuJnNvRNXXEmyLlXIvpMSVzG8mhN/taichi.mp4"
}

prediction = replicate.predictions.create(
  model="kwaivgi/kling-v2.6-motion-control",
  input=input
)

prediction = await replicate.predictions.async_create(
  model="kwaivgi/kling-v2.6-motion-control",
  input=input
)
mode
string
Video generation mode. 'std': Standard mode (cost-effective). 'pro': Professional mode (higher quality).

Default
"std"
image
uri
Reference image. The characters, backgrounds, and other elements in the generated video are based on the reference image. Supports .jpg/.jpeg/.png, max 10MB, dimensions 340px-3850px, aspect ratio 1:2.5 to 2.5:1.

video
uri
Reference video. The character actions in the generated video are consistent with the reference video. Supports .mp4/.mov, max 100MB, 3-30 seconds duration depending on character_orientation.

prompt
string
Text prompt for video generation. You can add elements to the screen and achieve motion effects through prompt words.

keep_original_sound
boolean
Whether to keep the original sound of the video

Default
true
character_orientation
string
Generate the orientation of the characters in the video. 'image': same orientation as the person in the picture (max 10s video). 'video': consistent with the orientation of the characters in the video (max 30s video).

Default
"image"
{
  "type": "object",
  "title": "Input",
  "required": [
    "image",
    "video"
  ],
  "properties": {
    "mode": {
      "enum": [
        "std",
        "pro"
      ],
      "type": "string",
      "title": "mode",
      "description": "Video generation mode. 'std': Standard mode (cost-effective). 'pro': Professional mode (higher quality).",
      "default": "std",
      "x-order": 4
    },
    "image": {
      "type": "string",
      "title": "Image",
      "format": "uri",
      "x-order": 1,
      "description": "Reference image. The characters, backgrounds, and other elements in the generated video are based on the reference image. Supports .jpg/.jpeg/.png, max 10MB, dimensions 340px-3850px, aspect ratio 1:2.5 to 2.5:1."
    },
    "video": {
      "type": "string",
      "title": "Video",
      "format": "uri",
      "x-order": 2,
      "description": "Reference video. The character actions in the generated video are consistent with the reference video. Supports .mp4/.mov, max 100MB, 3-30 seconds duration depending on character_orientation."
    },
    "prompt": {
      "type": "string",
      "title": "Prompt",
      "default": "",
      "x-order": 0,
      "description": "Text prompt for video generation. You can add elements to the screen and achieve motion effects through prompt words."
    },
    "keep_original_sound": {
      "type": "boolean",
      "title": "Keep Original Sound",
      "default": true,
      "x-order": 5,
      "description": "Whether to keep the original sound of the video"
    },
    "character_orientation": {
      "enum": [
        "image",
        "video"
      ],
      "type": "string",
      "title": "character_orientation",
      "description": "Generate the orientation of the characters in the video. 'image': same orientation as the person in the picture (max 10s video). 'video': consistent with the orientation of the characters in the video (max 30s video).",
      "default": "image",
      "x-order": 3
    }
  }
}
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
    "mode": "pro",
    "image": "https://replicate.delivery/pbxt/OHMFuZ6vHcDd3sXoOnn5oGLBvZIq43HuAige2XeWLdBigLUs/santa.png",
    "video": "https://replicate.delivery/pbxt/OHMFv2w6blsLcBTvRSEujuJnNvRNXXEmyLlXIvpMSVzG8mhN/taichi.mp4"
}

output = replicate.run(
    "kwaivgi/kling-v2.6-motion-control",
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

Copy

Cancel a prediction

predictions.cancel
Input parameters
prediction_id
string
Required
The ID of the prediction to cancel.
Examples

Cancel
Cancel an in progress prediction

Make a request
/predictions/{prediction_id}/cancel
import replicate

prediction = replicate.predictions.get(prediction_id)
prediction.cancel()
print(prediction)
#=> Prediction(id="xyz...", status="canceled", ... )

Copy

List predictions

predictions.list
Examples

List
List the first page of your predictions


Paginate
Make a request
/predictions
import replicate

predictions = replicate.predictions.list()
print(predictions.results)
#=> [Prediction(id="xyz...", status="successful", ... ), Prediction(id="abc...", status="successful", ... )]
