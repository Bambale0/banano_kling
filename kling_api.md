# Kling 3.0
документация по миграции с freepic на piapi.
от freepic отказываемся полность.
## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /api/v1/task:
    post:
      summary: Kling 3.0
      deprecated: false
      description: >-
        This is the api for Kling's video generation API. Kling 3.0 is a
        upgraded version of Kling 2.6.


        **Pricing**

        | Resolution | Enable audio | Price(USD) per second |

        | --- | --- | --- |

        | 720 | false | 0.1 |

        | 720 | true | 0.15 |

        | 1080 | false | 0.15 |

        | 1080 | true | 0.2 |


        Price example

        - generate a 10 second video of 720p without audio will cost: 10 \*
        \$0.10 \= \$1.0

        - generate a multi-shots video, shot1 2s, shot2 3s, 720p with audio will
        cost: \(2 \+ 3\) \* \$0.15 \= \$1.5


        **Note**

        - Support more flexible duration between 3 - 15 seconds

        - If multi shots used, param `prompt` and `duration` will be ignored

        - Maximum 6 multi shots, total duration should not exceed 15 seconds

        - response struct is different, see [Get
        Task](https://goapi.ai/docs/kling-api/get-task) for details
      tags:
        - Endpoints/Kling
      parameters:
        - name: x-api-key
          in: header
          description: you api key
          required: true
          example: ''
          schema:
            type: string
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                model:
                  type: string
                  default: kling
                  enum:
                    - kling
                  x-apidog-enum:
                    - value: kling
                      name: ''
                      description: ''
                task_type:
                  type: string
                  default: video_generation
                  enum:
                    - video_generation
                  x-apidog-enum:
                    - value: video_generation
                      name: ''
                      description: ''
                input:
                  type: object
                  description: |
                    the input param of the task
                  x-apidog-orders:
                    - prompt
                    - version
                    - mode
                    - image_url
                    - image_tail_url
                    - duration
                    - aspect_ratio
                    - enable_audio
                    - prefer_multi_shots
                    - multi_shots
                  properties:
                    prompt:
                      type: string
                      description: text prompt used to generate video
                    version:
                      type: string
                      description: must provide version 3.0
                      examples:
                        - '3.0'
                    mode:
                      type: string
                      enum:
                        - std
                        - pro
                      x-apidog-enum:
                        - value: std
                          name: ''
                          description: ''
                        - value: pro
                          name: ''
                          description: ''
                      default: std
                      description: std mode is 720p, pro mode is 1080p
                    image_url:
                      type: string
                      description: the image used as first frame
                    image_tail_url:
                      type: string
                      description: the image used as last frame
                    duration:
                      type: integer
                      description: duration of the generated video
                      default: 5
                      minimum: 3
                      maximum: 15
                    aspect_ratio:
                      type: string
                      enum:
                        - '16:9'
                        - '9:16'
                        - '1:1'
                      x-apidog-enum:
                        - value: '16:9'
                          name: ''
                          description: ''
                        - value: '9:16'
                          name: ''
                          description: ''
                        - value: '1:1'
                          name: ''
                          description: ''
                      default: '16:9'
                      description: >-
                        aspect ratio of the generated video, ignored if start
                        image provided
                    enable_audio:
                      type: boolean
                      description: generate audio if true
                    prefer_multi_shots:
                      type: boolean
                      description: more likely to generate multi-shots video if true
                    multi_shots:
                      type: array
                      items:
                        $ref: '#/components/schemas/Kling%20omni%20multi%20shot'
                      description: >-
                        give detail prompt and duration for each shot. will
                        ignore prompt and duration if given
                  required:
                    - prompt
                    - version
                  x-apidog-ignore-properties: []
                config:
                  type: object
                  properties:
                    webhook_config:
                      type: object
                      properties:
                        endpoint:
                          type: string
                        secret:
                          type: string
                      x-apidog-orders:
                        - endpoint
                        - secret
                      description: >-
                        Webhook provides timely task notifications. Check [PiAPI
                        webhook](/docs/unified-webhook) for detail.
                      x-apidog-ignore-properties: []
                    service_mode:
                      type: string
                      description: >
                        This allows users to choose whether this specific task
                        will get processed under PAYG or HYA mode. If
                        unspecified, then this task will get processed under
                        whatever mode (PAYG or HYA)
                         the user chose on the workspace setting of your account.
                        - `public` means this task will be processed under PAYG
                        mode.

                        - `private` means this task will be processed under HYA
                        mode.
                      enum:
                        - public
                        - private
                      x-apidog-enum:
                        - value: public
                          name: ''
                          description: means this task will be processed under PAYG mode.
                        - value: private
                          name: ''
                          description: >-
                            means this task will be processed under HYA
                            modesetting of your account.
                  x-apidog-orders:
                    - webhook_config
                    - service_mode
                  x-apidog-ignore-properties: []
              x-apidog-orders:
                - model
                - task_type
                - input
                - 01JZ4Z64RY9PZ6Z3P8K0BWV7TN
              required:
                - model
                - task_type
                - input
              x-apidog-refs:
                01JZ4Z64RY9PZ6Z3P8K0BWV7TN:
                  $ref: '#/components/schemas/config'
              x-apidog-ignore-properties:
                - config
            examples:
              '1':
                value:
                  model: kling
                  task_type: video_generation
                  input:
                    prompt: >-
                      Close-up, static camera, a woman in swim suit near the sea
                      is introducing herself.
                    duration: 5
                    aspect_ratio: '16:9'
                    enable_audio: false
                    prefer_multi_shots: false
                    mode: std
                    version: '3.0'
                  config:
                    service_mode: public
                    webhook_config:
                      endpoint: >-
                        https://webhook.site/64e7e8fa-a47a-4d30-b00a-8746d2d04590
                      secret: ''
                summary: basic usage
              '2':
                value:
                  model: kling
                  task_type: video_generation
                  input:
                    multi_shots:
                      - prompt: A dog running near the sea
                        duration: 3
                      - prompt: The dog stop before a cat on beach
                        duration: 2
                    prefer_multi_shots: true
                    aspect_ratio: '16:9'
                    enable_audio: true
                    mode: std
                    version: '3.0'
                  config:
                    service_mode: public
                    webhook_config:
                      endpoint: >-
                        https://webhook.site/5468eca8-1cad-4dd3-9799-b6fbd9770fda
                      secret: ''
                summary: custom multi shots
              '3':
                value:
                  model: kling
                  task_type: video_generation
                  input:
                    prompt: >-
                      The flowers gradually open in a gentle, time-lapse motion.
                      Make the video loop
                    image_url: https://piapi.ai/workspace/flux/input_example.png
                    image_tail_url: https://piapi.ai/workspace/flux/input_example.png
                    mode: std
                    version: '3.0'
                    duration: 5
                    enable_audio: false
                  config:
                    service_mode: public
                    webhook_config:
                      endpoint: >-
                        https://webhook.site/f10f2cd3-2109-4a4d-b82b-c0f1233e33a3
                      secret: '123456'
                summary: image to video
      responses:
        '200':
          description: ''
          content:
            application/json:
              schema:
                type: object
                properties: {}
                x-apidog-orders: []
                x-apidog-ignore-properties: []
              example:
                code: 200
                data:
                  task_id: 40680c72-279e-42c2-a4c0-e96e71865f04
                  model: kling
                  task_type: video_generation
                  status: pending
                  config:
                    service_mode: public
                    webhook_config:
                      endpoint: >-
                        https://webhook.site/5468eca8-1cad-4dd3-9799-b6fbd9770fda
                      secret: ''
                  input:
                    aspect_ratio: '16:9'
                    enable_audio: true
                    mode: std
                    multi_shots:
                      - duration: 3
                        prompt: A dog running near the sea
                      - duration: 2
                        prompt: The dog stop before a cat on beach
                    prefer_multi_shots: true
                    version: '3.0'
                  output:
                    video: ''
                  meta:
                    created_at: '2026-02-13T04:17:29.108326563Z'
                    started_at: '0001-01-01T00:00:00Z'
                    ended_at: '0001-01-01T00:00:00Z'
                    usage:
                      type: point
                      frozen: 10000000
                      consume: 0
                    is_using_private_pool: false
                  detail: null
                  logs: null
                  error:
                    code: 0
                    raw_message: ''
                    message: ''
                    detail: null
                message: success
          headers: {}
          x-apidog-name: Success
      security: []
      x-apidog-folder: Endpoints/Kling
      x-apidog-status: released
      x-run-in-apidog: https://app.apidog.com/web/project/675356/apis/api-28017121-run
components:
  schemas:
    Kling omni multi shot:
      type: object
      properties:
        prompt:
          type: string
          description: prompt of the shot
        duration:
          type: integer
          default: 3
          minimum: 1
          maximum: 14
          description: >-
            duraton of the shot, total duration of all shots should not exceed
            15
      x-apidog-orders:
        - prompt
        - duration
      required:
        - prompt
      x-apidog-ignore-properties: []
      x-apidog-folder: ''
    config:
      type: object
      properties:
        config:
          type: object
          properties:
            webhook_config:
              type: object
              properties:
                endpoint:
                  type: string
                secret:
                  type: string
              x-apidog-orders:
                - endpoint
                - secret
              description: >-
                Webhook provides timely task notifications. Check [PiAPI
                webhook](/docs/unified-webhook) for detail.
              x-apidog-ignore-properties: []
            service_mode:
              type: string
              description: >
                This allows users to choose whether this specific task will get
                processed under PAYG or HYA mode. If unspecified, then this task
                will get processed under whatever mode (PAYG or HYA)
                 the user chose on the workspace setting of your account.
                - `public` means this task will be processed under PAYG mode.

                - `private` means this task will be processed under HYA mode.
              enum:
                - public
                - private
              x-apidog-enum:
                - value: public
                  name: ''
                  description: means this task will be processed under PAYG mode.
                - value: private
                  name: ''
                  description: >-
                    means this task will be processed under HYA modesetting of
                    your account.
          x-apidog-orders:
            - webhook_config
            - service_mode
          x-apidog-ignore-properties: []
      x-apidog-orders:
        - config
      x-apidog-ignore-properties: []
      x-apidog-folder: ''
  securitySchemes: {}
servers:
  - url: https://api.piapi.ai
    description: Develop Env
security: []

```
# Get Task

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /api/v1/task/{task_id}:
    get:
      summary: Get Task
      deprecated: false
      description: >-
        This is provided as part of the [Kling API](https://piapi.ai/kling-api)
        from PiAPI. 

        This endpoint could get video generation progress or result of Kling
        task.
      operationId: kling-api/get-task
      tags:
        - Endpoints/Kling
      parameters:
        - name: task_id
          in: path
          description: ''
          required: true
          schema:
            type: string
        - name: x-api-key
          in: header
          description: Your API Key used for request authorization
          required: true
          example: ''
          schema:
            type: string
      responses:
        '200':
          description: ''
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                  data:
                    type: object
                    properties:
                      task_id:
                        type: string
                      model:
                        type: string
                      task_type:
                        type: string
                      status:
                        type: string
                        enum:
                          - Completed
                          - Processing
                          - Pending
                          - Failed
                          - Staged
                        x-apidog-enum:
                          - value: Completed
                            name: ''
                            description: ''
                          - value: Processing
                            name: ''
                            description: >-
                              Means that your jobs is currently being processed.
                              Number of "processing" jobs counts as part of the
                              "concurrent jobs"
                          - value: Pending
                            name: ''
                            description: >-
                              Means that we recognizes the jobs you sent should
                              be processed by MJ/Luma/Suno/Kling/etc but right
                              now none of the  account is available to receive
                              further jobs. During peak loads there can be
                              longer wait time to get your jobs from "pending"
                              to "processing". If reducing waiting time is your
                              primary concern, then a combination of
                              Pay-as-you-go and Host-your-own-account option
                              might suit you better.Number of "pending" jobs
                              counts as part of the "concurrent jobs"
                          - value: Failed
                            name: ''
                            description: Task failed. Check the error message for detail.
                          - value: Staged
                            name: ''
                            description: >-
                              A stage only in Midjourney task . Means that you
                              have exceeded the number of your "concurrent jobs"
                              limit and your jobs are being queuedNumber of
                              "staged" jobs does not count as part of the
                              "concurrent jobs". Also, please note the maximum
                              number of jobs in the "staged" queue is 50. So if
                              your operational needs exceed the 50 jobs limit,
                              then please create your own queuing system logic. 
                        description: >-
                          Hover on the "Completed" option and you coult see the
                          explaintion of all status:
                          completed/processing/pending/failed/staged
                      input:
                        type: object
                        properties: {}
                        x-apidog-orders: []
                        x-apidog-ignore-properties: []
                      output:
                        type: object
                        properties: {}
                        x-apidog-orders: []
                        x-apidog-ignore-properties: []
                      meta:
                        type: object
                        properties:
                          created_at:
                            type: string
                            description: >-
                              The time when the task was submitted to us (staged
                              and/or pending)
                          started_at:
                            type: string
                            description: >-
                              The time when the task started processing. the
                              time from created_at to time of started_at is time
                              the job spent in the "staged“ stage and/or
                              the"pending" stage if there were any.
                          ended_at:
                            type: string
                            description: The time when the task finished processing.
                          usage:
                            type: object
                            properties:
                              type:
                                type: string
                              frozen:
                                type: number
                              consume:
                                type: number
                            x-apidog-orders:
                              - type
                              - frozen
                              - consume
                            required:
                              - type
                              - frozen
                              - consume
                            x-apidog-ignore-properties: []
                          is_using_private_pool:
                            type: boolean
                        x-apidog-orders:
                          - created_at
                          - started_at
                          - ended_at
                          - usage
                          - is_using_private_pool
                        required:
                          - usage
                          - is_using_private_pool
                        x-apidog-ignore-properties: []
                      detail:
                        type: 'null'
                      logs:
                        type: array
                        items:
                          type: object
                          properties: {}
                          x-apidog-orders: []
                          x-apidog-ignore-properties: []
                      error:
                        type: object
                        properties:
                          code:
                            type: integer
                          message:
                            type: string
                        x-apidog-orders:
                          - code
                          - message
                        x-apidog-ignore-properties: []
                    x-apidog-orders:
                      - task_id
                      - model
                      - task_type
                      - status
                      - input
                      - output
                      - meta
                      - detail
                      - logs
                      - error
                    required:
                      - task_id
                      - model
                      - task_type
                      - status
                      - input
                      - output
                      - meta
                      - detail
                      - logs
                      - error
                    x-apidog-ignore-properties: []
                  message:
                    type: string
                    description: >-
                      If you get non-null error message, here are some steps you
                      chould follow:

                      - Check our [common error
                      message](https://climbing-adapter-afb.notion.site/Common-Error-Messages-6d108f5a8f644238b05ca50d47bbb0f4)

                      - Retry for several times

                      - If you have retried for more than 3 times and still not
                      work, file a ticket on Discord and our support will be
                      with you soon.
                x-apidog-orders:
                  - 01J8MXKN2C0FPCAMTSG8FV1PZ8
                required:
                  - code
                  - data
                  - message
                x-apidog-refs:
                  01J8MXKN2C0FPCAMTSG8FV1PZ8:
                    $ref: '#/components/schemas/Unified-Task-Response'
                x-apidog-ignore-properties:
                  - code
                  - data
                  - message
              examples:
                '1':
                  summary: kling
                  value:
                    code: 200
                    data:
                      task_id: b3efc0ab-3fdb-4b88-b20a-94eef777e125
                      model: kling
                      task_type: video_generation
                      status: completed
                      config:
                        service_mode: private
                        webhook_config:
                          endpoint: ''
                          secret: ''
                      input: {}
                      output:
                        type: m2v_txt2video_hq
                        status: 99
                        works:
                          - status: 99
                            type: m2v_txt2video_hq
                            cover:
                              resource: https://xxx.png
                              resource_without_watermark: ''
                              height: 1440
                              width: 1440
                              duration: 0
                            video:
                              resource: https://xxx.mp4
                              resource_without_watermark: https://storage.goapi.ai/xxx.mp4
                              height: 1440
                              width: 1440
                              duration: 5100
                      meta: {}
                      detail: null
                      logs: []
                      error:
                        code: 0
                        raw_message: ''
                        message: ''
                        detail: null
                    message: success
                '2':
                  summary: kling turbo
                  value:
                    timestamp: 1766571018
                    data:
                      task_id: 98aad4db-41a1-42ca-b06a-aa77714b4ff8
                      model: kling-turbo
                      task_type: video_generation
                      status: completed
                      config:
                        service_mode: ''
                        webhook_config:
                          endpoint: >-
                            https://webhook.site/20d9b15f-bfb8-4237-8e4a-993f462f9eb9
                          secret: ''
                      input:
                        aspect_ratio: '16:9'
                        duration: 5
                        prompt: >-
                          Close-up, static camera, a woman in swim suit near the
                          sea is introducing herself.
                      output:
                        video: >-
                          https://img.theapi.app/ephemeral/fe08dad8-f79b-44ce-9fe5-c1e7fd14d45a.mp4
                      meta:
                        created_at: '2025-12-24T10:08:00.260200381Z'
                        started_at: '2025-12-24T10:08:01.091506008Z'
                        ended_at: '2025-12-24T10:10:18.112349385Z'
                        usage:
                          type: llm
                          frozen: 0
                          consume: 2800000
                        is_using_private_pool: false
                      detail: null
                      logs: []
                      error:
                        code: 0
                        raw_message: ''
                        message: ''
                        detail: null
                '3':
                  summary: kling motion control
                '4':
                  summary: kling motion control
                  value:
                    timestamp: 1767705595
                    data:
                      task_id: 820b72ec-5235-4315-a3ea-cf95057787b8
                      model: kling
                      task_type: motion_control
                      status: completed
                      config:
                        service_mode: public
                        webhook_config:
                          endpoint: >-
                            https://webhook.site/ce576103-6cd3-43a6-8aac-c8f0dc13adc0
                          secret: ''
                      input:
                        image_url: https://example.com/kling/digital/image/Isabella.png
                        keep_original_sound: true
                        mode: std
                        motion_direction: video
                        preset_motion: Heart Gesture Dance
                        version: '2.6'
                        video_url: ''
                      output:
                        video_url: https://storage.theapi.app/videos/299676610318135.mp4
                        type: m2v_motion_control
                        status: 99
                        works:
                          - content_type: video
                            status: 99
                            type: m2v_motion_control
                            cover:
                              resource: >-
                                https://s15-kling.klingai.com/kimg/EMXN1y8qYwoGdXBsb2FkEg55bGFiLXN0dW50LXNncBpJNTU3YTEzNTktY2I1MC00NzkxLWEzZWItODg3MThhNTNkNDIzLXhacEdFUGFQaHlOdjhCODRqUE1wZGctb3V0cHV0X2ZmLmpwZw.origin?x-kcdn-pid=112372
                              resource_without_watermark: ''
                              height: 1280
                              width: 720
                              duration: 0
                            video:
                              resource: >-
                                https://v15-kling.klingai.com/bs2/upload-ylab-stunt-sgp/557a1359-cb50-4791-a3eb-88718a53d423-xZpGEPaPhyNv8B84jPMpdg-output.mp4?x-kcdn-pid=112372
                              resource_without_watermark: >-
                                https://storage.theapi.app/videos/299676610318135.mp4
                              height: 1280
                              width: 720
                              duration: 8766
                      meta:
                        created_at: '2026-01-06T13:11:22.513893572Z'
                        started_at: '2026-01-06T13:11:23.45584817Z'
                        ended_at: '2026-01-06T13:19:55.707304033Z'
                        usage:
                          type: point
                          frozen: 5850000
                          consume: 5850000
                        is_using_private_pool: false
                      detail: null
                      logs: null
                      error:
                        code: 0
                        raw_message: ''
                        message: ''
                        detail: null
                '5':
                  summary: Kling 3.0
                  value:
                    timestamp: 1770952944
                    data:
                      task_id: 259da62f-9516-4e44-82d6-ce747267a44c
                      model: kling
                      task_type: video_generation
                      status: completed
                      config:
                        service_mode: public
                        webhook_config:
                          endpoint: >-
                            https://webhook.site/64e7e8fa-a47a-4d30-b00a-8746d2d04590
                          secret: ''
                      input:
                        aspect_ratio: '16:9'
                        duration: 5
                        enable_audio: false
                        mode: std
                        prompt: >-
                          Close-up, static camera, a woman in swim suit near the
                          sea is introducing herself.
                        version: '3.0'
                      output:
                        video: https://storage.theapi.app/videos/302924319317897.mp4
                      meta:
                        created_at: '2026-02-13T03:20:33.392553085Z'
                        started_at: '2026-02-13T03:20:34.305168282Z'
                        ended_at: '2026-02-13T03:22:24.64542152Z'
                        usage:
                          type: point
                          frozen: 0
                          consume: 7500000
                        is_using_private_pool: false
                      detail: null
                      logs: null
                      error:
                        code: 0
                        raw_message: ''
                        message: ''
                        detail: null
          headers: {}
          x-apidog-name: Success
      security: []
      x-apidog-folder: Endpoints/Kling
      x-apidog-status: released
      x-run-in-apidog: https://app.apidog.com/web/project/675356/apis/api-10275890-run
components:
  schemas:
    Unified-Task-Response:
      type: object
      properties:
        code:
          type: integer
        data:
          type: object
          properties:
            task_id:
              type: string
            model:
              type: string
            task_type:
              type: string
            status:
              type: string
              enum:
                - Completed
                - Processing
                - Pending
                - Failed
                - Staged
              x-apidog-enum:
                - value: Completed
                  name: ''
                  description: ''
                - value: Processing
                  name: ''
                  description: >-
                    Means that your jobs is currently being processed. Number of
                    "processing" jobs counts as part of the "concurrent jobs"
                - value: Pending
                  name: ''
                  description: >-
                    Means that we recognizes the jobs you sent should be
                    processed by MJ/Luma/Suno/Kling/etc but right now none of
                    the  account is available to receive further jobs. During
                    peak loads there can be longer wait time to get your jobs
                    from "pending" to "processing". If reducing waiting time is
                    your primary concern, then a combination of Pay-as-you-go
                    and Host-your-own-account option might suit you
                    better.Number of "pending" jobs counts as part of the
                    "concurrent jobs"
                - value: Failed
                  name: ''
                  description: Task failed. Check the error message for detail.
                - value: Staged
                  name: ''
                  description: >-
                    A stage only in Midjourney task . Means that you have
                    exceeded the number of your "concurrent jobs" limit and your
                    jobs are being queuedNumber of "staged" jobs does not count
                    as part of the "concurrent jobs". Also, please note the
                    maximum number of jobs in the "staged" queue is 50. So if
                    your operational needs exceed the 50 jobs limit, then please
                    create your own queuing system logic. 
              description: >-
                Hover on the "Completed" option and you coult see the
                explaintion of all status:
                completed/processing/pending/failed/staged
            input:
              type: object
              properties: {}
              x-apidog-orders: []
              x-apidog-ignore-properties: []
            output:
              type: object
              properties: {}
              x-apidog-orders: []
              x-apidog-ignore-properties: []
            meta:
              type: object
              properties:
                created_at:
                  type: string
                  description: >-
                    The time when the task was submitted to us (staged and/or
                    pending)
                started_at:
                  type: string
                  description: >-
                    The time when the task started processing. the time from
                    created_at to time of started_at is time the job spent in
                    the "staged“ stage and/or the"pending" stage if there were
                    any.
                ended_at:
                  type: string
                  description: The time when the task finished processing.
                usage:
                  type: object
                  properties:
                    type:
                      type: string
                    frozen:
                      type: number
                    consume:
                      type: number
                  x-apidog-orders:
                    - type
                    - frozen
                    - consume
                  required:
                    - type
                    - frozen
                    - consume
                  x-apidog-ignore-properties: []
                is_using_private_pool:
                  type: boolean
              x-apidog-orders:
                - created_at
                - started_at
                - ended_at
                - usage
                - is_using_private_pool
              required:
                - usage
                - is_using_private_pool
              x-apidog-ignore-properties: []
            detail:
              type: 'null'
            logs:
              type: array
              items:
                type: object
                properties: {}
                x-apidog-orders: []
                x-apidog-ignore-properties: []
            error:
              type: object
              properties:
                code:
                  type: integer
                message:
                  type: string
              x-apidog-orders:
                - code
                - message
              x-apidog-ignore-properties: []
          x-apidog-orders:
            - task_id
            - model
            - task_type
            - status
            - input
            - output
            - meta
            - detail
            - logs
            - error
          required:
            - task_id
            - model
            - task_type
            - status
            - input
            - output
            - meta
            - detail
            - logs
            - error
          x-apidog-ignore-properties: []
        message:
          type: string
          description: >-
            If you get non-null error message, here are some steps you chould
            follow:

            - Check our [common error
            message](https://climbing-adapter-afb.notion.site/Common-Error-Messages-6d108f5a8f644238b05ca50d47bbb0f4)

            - Retry for several times

            - If you have retried for more than 3 times and still not work, file
            a ticket on Discord and our support will be with you soon.
      x-examples:
        Example 1:
          code: 200
          data:
            task_id: 49638cd2-4689-4f33-9336-164a8f6b1111
            model: Qubico/flux1-dev
            task_type: txt2img
            status: pending
            input:
              prompt: a bear
            output: null
            meta:
              account_id: 0
              account_name: Qubico_test_user
              created_at: '2024-08-16T16:13:21.194049Z'
              started_at: ''
              completed_at: ''
            detail: null
            logs: []
            error:
              code: 0
              message: ''
          message: success
      x-apidog-orders:
        - code
        - data
        - message
      required:
        - code
        - data
        - message
      x-apidog-ignore-properties: []
      x-apidog-folder: ''
  securitySchemes: {}
servers:
  - url: https://api.piapi.ai
    description: Develop Env
security: []

```
# Kling Motion Control

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /api/v1/task:
    post:
      summary: Kling Motion Control
      deprecated: false
      description: >-
        This is the api for Kling's Motion Control video generation API.


        **Pricing**

        According to the duration of input motion video(preset or uploaded)

        - std: $0.065 per second

        - pro: $0.104 per second


        **Note**

        - Currently only version 2.6 supports motion control

        - One of `video_url` and `preset_motion` must be provided as motion
        reference
      tags:
        - Endpoints/Kling
      parameters:
        - name: x-api-key
          in: header
          description: you api key
          required: true
          example: ''
          schema:
            type: string
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                model:
                  type: string
                  description: should be `kling`
                  default: kling
                  enum:
                    - kling
                  x-apidog-enum:
                    - value: kling
                      name: ''
                      description: ''
                task_type:
                  type: string
                  description: should be `motion_control`
                  default: motion_control
                  enum:
                    - motion_control
                  x-apidog-enum:
                    - value: motion_control
                      name: ''
                      description: ''
                input:
                  type: object
                  description: |
                    the input param of the task
                  x-apidog-orders:
                    - image_url
                    - video_url
                    - preset_motion
                    - motion_direction
                    - keep_original_sound
                    - mode
                  properties:
                    image_url:
                      type: string
                      description: the image of avatar
                    video_url:
                      type: string
                      description: the motion video url
                    preset_motion:
                      type: string
                      description: preset motion name, if provided will ignore video_url
                      enum:
                        - Cute Baby Dance
                        - Nezha
                        - Heart Gesture Dance
                        - Motorcycle Dance
                        - Subject 3 Dance
                        - Ghost Step Dance
                        - Martial Arts
                        - Running
                        - Poping
                      x-apidog-enum:
                        - value: Cute Baby Dance
                          name: ''
                          description: ''
                        - value: Nezha
                          name: ''
                          description: ''
                        - value: Heart Gesture Dance
                          name: ''
                          description: ''
                        - value: Motorcycle Dance
                          name: ''
                          description: ''
                        - value: Subject 3 Dance
                          name: ''
                          description: ''
                        - value: Ghost Step Dance
                          name: ''
                          description: ''
                        - value: Martial Arts
                          name: ''
                          description: ''
                        - value: Running
                          name: ''
                          description: ''
                        - value: Poping
                          name: ''
                          description: ''
                    motion_direction:
                      type: string
                      enum:
                        - video
                        - image
                      x-apidog-enum:
                        - value: video
                          name: ''
                          description: ''
                        - value: image
                          name: ''
                          description: ''
                      default: video
                      description: >-
                        when character orientation matches the video, complex
                        motions perform better; when it matches the image,
                        camera movements are better supported.
                    keep_original_sound:
                      type: boolean
                      description: keep motion video(preset or uploaded) audio if true
                    mode:
                      type: string
                      enum:
                        - std
                        - pro
                      x-apidog-enum:
                        - value: std
                          name: ''
                          description: ''
                        - value: pro
                          name: ''
                          description: ''
                      default: std
                      description: mode to generate video
                  required:
                    - image_url
                  x-apidog-ignore-properties: []
                config:
                  type: object
                  properties:
                    webhook_config:
                      type: object
                      properties:
                        endpoint:
                          type: string
                        secret:
                          type: string
                      x-apidog-orders:
                        - endpoint
                        - secret
                      description: >-
                        Webhook provides timely task notifications. Check [PiAPI
                        webhook](/docs/unified-webhook) for detail.
                      x-apidog-ignore-properties: []
                    service_mode:
                      type: string
                      description: >
                        This allows users to choose whether this specific task
                        will get processed under PAYG or HYA mode. If
                        unspecified, then this task will get processed under
                        whatever mode (PAYG or HYA)
                         the user chose on the workspace setting of your account.
                        - `public` means this task will be processed under PAYG
                        mode.

                        - `private` means this task will be processed under HYA
                        mode.
                      enum:
                        - public
                        - private
                      x-apidog-enum:
                        - value: public
                          name: ''
                          description: means this task will be processed under PAYG mode.
                        - value: private
                          name: ''
                          description: >-
                            means this task will be processed under HYA
                            modesetting of your account.
                  x-apidog-orders:
                    - webhook_config
                    - service_mode
                  x-apidog-ignore-properties: []
              x-apidog-orders:
                - model
                - task_type
                - input
                - 01JZ4Z64RY9PZ6Z3P8K0BWV7TN
              required:
                - model
                - task_type
                - input
              x-apidog-refs:
                01JZ4Z64RY9PZ6Z3P8K0BWV7TN:
                  $ref: '#/components/schemas/config'
              x-apidog-ignore-properties:
                - config
            example:
              model: kling
              task_type: motion_control
              input:
                image_url: https://example.com/kling/digital/image/Isabella.png
                video_url: ''
                preset_motion: Heart Gesture Dance
                motion_direction: video
                keep_original_sound: true
                mode: std
                version: '2.6'
              config:
                service_mode: public
                webhook_config:
                  endpoint: https://webhook.site/ce576103-6cd3-43a6-8aac-c8f0dc13adc0
                  secret: ''
      responses:
        '200':
          description: ''
          content:
            application/json:
              schema:
                type: object
                properties: {}
                x-apidog-orders: []
                x-apidog-ignore-properties: []
              example:
                code: 200
                data:
                  task_id: 820b72ec-5235-4315-a3ea-cf95057787b8
                  model: kling
                  task_type: motion_control
                  status: pending
                  config:
                    service_mode: public
                    webhook_config:
                      endpoint: >-
                        https://webhook.site/ce576103-6cd3-43a6-8aac-c8f0dc13adc0
                      secret: ''
                  input:
                    image_url: https://example.com/kling/digital/image/Isabella.png
                    keep_original_sound: true
                    mode: std
                    motion_direction: video
                    preset_motion: Heart Gesture Dance
                    version: '2.6'
                    video_url: ''
                  output:
                    type: ''
                    status: 0
                    works: null
                  meta:
                    created_at: '2026-01-06T13:11:22.513893572Z'
                    started_at: '0001-01-01T00:00:00Z'
                    ended_at: '0001-01-01T00:00:00Z'
                    usage:
                      type: point
                      frozen: 0
                      consume: 0
                    is_using_private_pool: false
                  detail: null
                  logs: null
                  error:
                    code: 0
                    raw_message: ''
                    message: ''
                    detail: null
                message: success
          headers: {}
          x-apidog-name: Success
      security: []
      x-apidog-folder: Endpoints/Kling
      x-apidog-status: released
      x-run-in-apidog: https://app.apidog.com/web/project/675356/apis/api-26374403-run
components:
  schemas:
    config:
      type: object
      properties:
        config:
          type: object
          properties:
            webhook_config:
              type: object
              properties:
                endpoint:
                  type: string
                secret:
                  type: string
              x-apidog-orders:
                - endpoint
                - secret
              description: >-
                Webhook provides timely task notifications. Check [PiAPI
                webhook](/docs/unified-webhook) for detail.
              x-apidog-ignore-properties: []
            service_mode:
              type: string
              description: >
                This allows users to choose whether this specific task will get
                processed under PAYG or HYA mode. If unspecified, then this task
                will get processed under whatever mode (PAYG or HYA)
                 the user chose on the workspace setting of your account.
                - `public` means this task will be processed under PAYG mode.

                - `private` means this task will be processed under HYA mode.
              enum:
                - public
                - private
              x-apidog-enum:
                - value: public
                  name: ''
                  description: means this task will be processed under PAYG mode.
                - value: private
                  name: ''
                  description: >-
                    means this task will be processed under HYA modesetting of
                    your account.
          x-apidog-orders:
            - webhook_config
            - service_mode
          x-apidog-ignore-properties: []
      x-apidog-orders:
        - config
      x-apidog-ignore-properties: []
      x-apidog-folder: ''
  securitySchemes: {}
servers:
  - url: https://api.piapi.ai
    description: Develop Env
security: []

```
# Kling 3.0 omni

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /api/v1/task:
    post:
      summary: Kling 3.0 omni
      deprecated: false
      description: >-
        This is the api for Kling's video generation API. Kling 3.0 Omni is a
        upgraded version of Kling o1.


        **Pricing**

        According to the resolution and duration of generated video


        ***A price reduction is applied for this API on 2026/2/13.***


        | Resolution | Enable audio | Price(USD) per second |

        | --- | --- | --- |

        | 720 | false | 0.1 |

        | 720 | true | 0.15 |

        | 1080 | false | 0.15 |

        | 1080 | true | 0.2 |


        Price example

        - generate a 10 second video of 720p without audio will cost: 10 \*
        \$0.10 \= \$1.0

        - generate a multi-shots video, shot1 2s, shot2 3s, 720p with audio will
        cost: \(2 \+ 3\) \* \$0.15 \= \$1.5



        **Note**

        - If multi shots used, param `prompt` and `duration` will be ignored

        - Maximum 6 multi shots, total duration should not exceed 15 seconds

        - if ref images provided, use @image_i in prompt to reference. i starts
        at 1, so use @image_1 for the first image in images list, @image_2 for
        the second image, etc.

        - ref images can be used multiple times in prompt, for example: use
        @image_1 as start frame, a woman @image_2 is introducing herself, and
        use @image_1 as end frame
      tags:
        - Endpoints/Kling omni
      parameters:
        - name: x-api-key
          in: header
          description: you api key
          required: true
          example: ''
          schema:
            type: string
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                model:
                  type: string
                  default: kling
                  enum:
                    - kling
                  x-apidog-enum:
                    - value: kling
                      name: ''
                      description: ''
                task_type:
                  type: string
                  default: omni_video_generation
                  enum:
                    - omni_video_generation
                  x-apidog-enum:
                    - value: omni_video_generation
                      name: ''
                      description: ''
                input:
                  type: object
                  description: |
                    the input param of the task
                  x-apidog-orders:
                    - prompt
                    - version
                    - resolution
                    - duration
                    - aspect_ratio
                    - enable_audio
                    - multi_shots
                    - images
                  properties:
                    prompt:
                      type: string
                      description: text prompt used to generate video
                    version:
                      type: string
                      enum:
                        - '3.0'
                      x-apidog-enum:
                        - value: '3.0'
                          name: ''
                          description: ''
                    resolution:
                      type: string
                      enum:
                        - 720p
                        - 1080p
                      x-apidog-enum:
                        - value: 720p
                          name: ''
                          description: ''
                        - value: 1080p
                          name: ''
                          description: ''
                      default: 720p
                    duration:
                      type: integer
                      description: duration of the generated video
                      default: 5
                      minimum: 3
                      maximum: 15
                    aspect_ratio:
                      type: string
                      enum:
                        - '16:9'
                        - '9:16'
                        - '1:1'
                      x-apidog-enum:
                        - value: '16:9'
                          name: ''
                          description: ''
                        - value: '9:16'
                          name: ''
                          description: ''
                        - value: '1:1'
                          name: ''
                          description: ''
                      default: '16:9'
                      description: aspect ratio of the generated video
                    enable_audio:
                      type: boolean
                      default: false
                    multi_shots:
                      type: array
                      items:
                        $ref: '#/components/schemas/Kling%20omni%20multi%20shot'
                      description: >-
                        describe multi shots. prompt and duration will be
                        ignored if used
                    images:
                      type: array
                      items:
                        type: string
                        description: valid image url for reference
                      description: must use @image_i in prompt to reference, i starts at 1
                  x-apidog-ignore-properties: []
                config:
                  type: object
                  properties:
                    webhook_config:
                      type: object
                      properties:
                        endpoint:
                          type: string
                        secret:
                          type: string
                      x-apidog-orders:
                        - endpoint
                        - secret
                      description: >-
                        Webhook provides timely task notifications. Check [PiAPI
                        webhook](/docs/unified-webhook) for detail.
                      x-apidog-ignore-properties: []
                    service_mode:
                      type: string
                      description: >
                        This allows users to choose whether this specific task
                        will get processed under PAYG or HYA mode. If
                        unspecified, then this task will get processed under
                        whatever mode (PAYG or HYA)
                         the user chose on the workspace setting of your account.
                        - `public` means this task will be processed under PAYG
                        mode.

                        - `private` means this task will be processed under HYA
                        mode.
                      enum:
                        - public
                        - private
                      x-apidog-enum:
                        - value: public
                          name: ''
                          description: means this task will be processed under PAYG mode.
                        - value: private
                          name: ''
                          description: >-
                            means this task will be processed under HYA
                            modesetting of your account.
                  x-apidog-orders:
                    - webhook_config
                    - service_mode
                  x-apidog-ignore-properties: []
              x-apidog-orders:
                - model
                - task_type
                - input
                - 01JZ4Z64RY9PZ6Z3P8K0BWV7TN
              required:
                - model
                - task_type
                - input
              x-apidog-refs:
                01JZ4Z64RY9PZ6Z3P8K0BWV7TN:
                  $ref: '#/components/schemas/config'
              x-apidog-ignore-properties:
                - config
            examples:
              '1':
                value:
                  model: kling
                  task_type: omni_video_generation
                  input:
                    prompt: >-
                      Close-up, static camera, a woman in swim suit near the sea
                      is introducing herself.
                    version: '3.0'
                    resolution: 720p
                    duration: 3
                    aspect_ratio: '16:9'
                    enable_audio: false
                  config:
                    service_mode: public
                    webhook_config:
                      endpoint: >-
                        https://webhook.site/5468eca8-1cad-4dd3-9799-b6fbd9770fda
                      secret: ''
                summary: text to video
              '2':
                value:
                  model: kling
                  task_type: omni_video_generation
                  input:
                    multi_shots:
                      - prompt: a dog stands near sea
                        duration: 2
                      - prompt: the dog turns around and walks on beach
                        duration: 3
                    version: '3.0'
                    resolution: 720p
                    aspect_ratio: '16:9'
                    enable_audio: true
                  config:
                    service_mode: public
                    webhook_config:
                      endpoint: >-
                        https://webhook.site/5468eca8-1cad-4dd3-9799-b6fbd9770fda
                      secret: ''
                summary: multi shots
              '3':
                value:
                  model: kling
                  task_type: omni_video_generation
                  input:
                    prompt: >-
                      A woman and a child are doing interview at New York
                      street. Use @image_1 as first frame
                    images:
                      - https://piapi.ai/workspace/qwen/txt_output_example.png
                    version: '3.0'
                    resolution: 720p
                    duration: 3
                    aspect_ratio: '16:9'
                    enable_audio: false
                  config:
                    service_mode: public
                    webhook_config:
                      endpoint: >-
                        https://webhook.site/5468eca8-1cad-4dd3-9799-b6fbd9770fda
                      secret: ''
                summary: image to video
      responses:
        '200':
          description: ''
          content:
            application/json:
              schema:
                type: object
                properties: {}
                x-apidog-orders: []
                x-apidog-ignore-properties: []
              example:
                code: 200
                data:
                  task_id: 5a9b4d8f-6f1c-460d-b295-ab1d663f9b90
                  model: kling
                  task_type: omni_video_generation
                  status: pending
                  config:
                    service_mode: public
                    webhook_config:
                      endpoint: >-
                        https://webhook.site/5468eca8-1cad-4dd3-9799-b6fbd9770fda
                      secret: ''
                  input:
                    aspect_ratio: '16:9'
                    enable_audio: true
                    multi_shots:
                      - duration: 2
                        prompt: a dog stands near sea
                      - duration: 3
                        prompt: the dog turns around and walks on beach
                    resolution: 720p
                    version: '3.0'
                  output:
                    video: ''
                  meta:
                    created_at: '2026-02-07T02:31:17.998381738Z'
                    started_at: '0001-01-01T00:00:00Z'
                    ended_at: '0001-01-01T00:00:00Z'
                    usage:
                      type: point
                      frozen: 10000000
                      consume: 0
                    is_using_private_pool: false
                  detail: null
                  logs: null
                  error:
                    code: 0
                    raw_message: ''
                    message: ''
                    detail: null
                message: success
          headers: {}
          x-apidog-name: Success
      security: []
      x-apidog-folder: Endpoints/Kling omni
      x-apidog-status: released
      x-run-in-apidog: https://app.apidog.com/web/project/675356/apis/api-27719117-run
components:
  schemas:
    Kling omni multi shot:
      type: object
      properties:
        prompt:
          type: string
          description: prompt of the shot
        duration:
          type: integer
          default: 3
          minimum: 1
          maximum: 14
          description: >-
            duraton of the shot, total duration of all shots should not exceed
            15
      x-apidog-orders:
        - prompt
        - duration
      required:
        - prompt
      x-apidog-ignore-properties: []
      x-apidog-folder: ''
    config:
      type: object
      properties:
        config:
          type: object
          properties:
            webhook_config:
              type: object
              properties:
                endpoint:
                  type: string
                secret:
                  type: string
              x-apidog-orders:
                - endpoint
                - secret
              description: >-
                Webhook provides timely task notifications. Check [PiAPI
                webhook](/docs/unified-webhook) for detail.
              x-apidog-ignore-properties: []
            service_mode:
              type: string
              description: >
                This allows users to choose whether this specific task will get
                processed under PAYG or HYA mode. If unspecified, then this task
                will get processed under whatever mode (PAYG or HYA)
                 the user chose on the workspace setting of your account.
                - `public` means this task will be processed under PAYG mode.

                - `private` means this task will be processed under HYA mode.
              enum:
                - public
                - private
              x-apidog-enum:
                - value: public
                  name: ''
                  description: means this task will be processed under PAYG mode.
                - value: private
                  name: ''
                  description: >-
                    means this task will be processed under HYA modesetting of
                    your account.
          x-apidog-orders:
            - webhook_config
            - service_mode
          x-apidog-ignore-properties: []
      x-apidog-orders:
        - config
      x-apidog-ignore-properties: []
      x-apidog-folder: ''
  securitySchemes: {}
servers:
  - url: https://api.piapi.ai
    description: Develop Env
security: []

```
# Get Task

## OpenAPI Specification

```yaml
openapi: 3.0.1
info:
  title: ''
  description: ''
  version: 1.0.0
paths:
  /api/v1/task/{task_id}:
    get:
      summary: Get Task
      deprecated: false
      description: >-
        This is provided as part of the [Kling API](https://piapi.ai/kling-api)
        from PiAPI. 

        This endpoint could get video generation progress or result of Kling
        task.
      operationId: kling-api/get-task
      tags:
        - Endpoints/Kling omni
      parameters:
        - name: task_id
          in: path
          description: ''
          required: true
          schema:
            type: string
        - name: x-api-key
          in: header
          description: Your API Key used for request authorization
          required: true
          example: ''
          schema:
            type: string
      responses:
        '200':
          description: ''
          content:
            application/json:
              schema:
                type: object
                properties:
                  code:
                    type: integer
                  data:
                    type: object
                    properties:
                      task_id:
                        type: string
                      model:
                        type: string
                      task_type:
                        type: string
                      status:
                        type: string
                        enum:
                          - Completed
                          - Processing
                          - Pending
                          - Failed
                          - Staged
                        x-apidog-enum:
                          - value: Completed
                            name: ''
                            description: ''
                          - value: Processing
                            name: ''
                            description: >-
                              Means that your jobs is currently being processed.
                              Number of "processing" jobs counts as part of the
                              "concurrent jobs"
                          - value: Pending
                            name: ''
                            description: >-
                              Means that we recognizes the jobs you sent should
                              be processed by MJ/Luma/Suno/Kling/etc but right
                              now none of the  account is available to receive
                              further jobs. During peak loads there can be
                              longer wait time to get your jobs from "pending"
                              to "processing". If reducing waiting time is your
                              primary concern, then a combination of
                              Pay-as-you-go and Host-your-own-account option
                              might suit you better.Number of "pending" jobs
                              counts as part of the "concurrent jobs"
                          - value: Failed
                            name: ''
                            description: Task failed. Check the error message for detail.
                          - value: Staged
                            name: ''
                            description: >-
                              A stage only in Midjourney task . Means that you
                              have exceeded the number of your "concurrent jobs"
                              limit and your jobs are being queuedNumber of
                              "staged" jobs does not count as part of the
                              "concurrent jobs". Also, please note the maximum
                              number of jobs in the "staged" queue is 50. So if
                              your operational needs exceed the 50 jobs limit,
                              then please create your own queuing system logic. 
                        description: >-
                          Hover on the "Completed" option and you coult see the
                          explaintion of all status:
                          completed/processing/pending/failed/staged
                      input:
                        type: object
                        properties: {}
                        x-apidog-orders: []
                        x-apidog-ignore-properties: []
                      output:
                        type: object
                        properties: {}
                        x-apidog-orders: []
                        x-apidog-ignore-properties: []
                      meta:
                        type: object
                        properties:
                          created_at:
                            type: string
                            description: >-
                              The time when the task was submitted to us (staged
                              and/or pending)
                          started_at:
                            type: string
                            description: >-
                              The time when the task started processing. the
                              time from created_at to time of started_at is time
                              the job spent in the "staged“ stage and/or
                              the"pending" stage if there were any.
                          ended_at:
                            type: string
                            description: The time when the task finished processing.
                          usage:
                            type: object
                            properties:
                              type:
                                type: string
                              frozen:
                                type: number
                              consume:
                                type: number
                            x-apidog-orders:
                              - type
                              - frozen
                              - consume
                            required:
                              - type
                              - frozen
                              - consume
                            x-apidog-ignore-properties: []
                          is_using_private_pool:
                            type: boolean
                        x-apidog-orders:
                          - created_at
                          - started_at
                          - ended_at
                          - usage
                          - is_using_private_pool
                        required:
                          - usage
                          - is_using_private_pool
                        x-apidog-ignore-properties: []
                      detail:
                        type: 'null'
                      logs:
                        type: array
                        items:
                          type: object
                          properties: {}
                          x-apidog-orders: []
                          x-apidog-ignore-properties: []
                      error:
                        type: object
                        properties:
                          code:
                            type: integer
                          message:
                            type: string
                        x-apidog-orders:
                          - code
                          - message
                        x-apidog-ignore-properties: []
                    x-apidog-orders:
                      - task_id
                      - model
                      - task_type
                      - status
                      - input
                      - output
                      - meta
                      - detail
                      - logs
                      - error
                    required:
                      - task_id
                      - model
                      - task_type
                      - status
                      - input
                      - output
                      - meta
                      - detail
                      - logs
                      - error
                    x-apidog-ignore-properties: []
                  message:
                    type: string
                    description: >-
                      If you get non-null error message, here are some steps you
                      chould follow:

                      - Check our [common error
                      message](https://climbing-adapter-afb.notion.site/Common-Error-Messages-6d108f5a8f644238b05ca50d47bbb0f4)

                      - Retry for several times

                      - If you have retried for more than 3 times and still not
                      work, file a ticket on Discord and our support will be
                      with you soon.
                x-apidog-orders:
                  - 01J8MXKN2C0FPCAMTSG8FV1PZ8
                required:
                  - code
                  - data
                  - message
                x-apidog-refs:
                  01J8MXKN2C0FPCAMTSG8FV1PZ8:
                    $ref: '#/components/schemas/Unified-Task-Response'
                x-apidog-ignore-properties:
                  - code
                  - data
                  - message
              example:
                timestamp: 1770423368
                data:
                  task_id: f43657f9-5655-4869-a201-651ded8649bb
                  model: kling
                  task_type: omni_video_generation
                  status: completed
                  config:
                    service_mode: public
                    webhook_config:
                      endpoint: >-
                        https://webhook.site/5468eca8-1cad-4dd3-9799-b6fbd9770fda
                      secret: ''
                  input:
                    aspect_ratio: '16:9'
                    duration: 5
                    prompt: >-
                      Close-up, static camera, a woman in swim suit near the sea
                      is introducing herself.
                    resolution: 720p
                    version: o1
                  output:
                    video: https://storage.theapi.app/videos/302394780311449.mp4
                  meta:
                    created_at: '2026-02-07T00:14:45.539719292Z'
                    started_at: '2026-02-07T00:14:45.759947942Z'
                    ended_at: '2026-02-07T00:16:08.628146393Z'
                    usage:
                      type: point
                      frozen: 3900000
                      consume: 3900000
                    is_using_private_pool: false
                  detail: null
                  logs: null
                  error:
                    code: 0
                    raw_message: ''
                    message: ''
                    detail: null
          headers: {}
          x-apidog-name: Success
      security: []
      x-apidog-folder: Endpoints/Kling omni
      x-apidog-status: released
      x-run-in-apidog: https://app.apidog.com/web/project/675356/apis/api-27719115-run
components:
  schemas:
    Unified-Task-Response:
      type: object
      properties:
        code:
          type: integer
        data:
          type: object
          properties:
            task_id:
              type: string
            model:
              type: string
            task_type:
              type: string
            status:
              type: string
              enum:
                - Completed
                - Processing
                - Pending
                - Failed
                - Staged
              x-apidog-enum:
                - value: Completed
                  name: ''
                  description: ''
                - value: Processing
                  name: ''
                  description: >-
                    Means that your jobs is currently being processed. Number of
                    "processing" jobs counts as part of the "concurrent jobs"
                - value: Pending
                  name: ''
                  description: >-
                    Means that we recognizes the jobs you sent should be
                    processed by MJ/Luma/Suno/Kling/etc but right now none of
                    the  account is available to receive further jobs. During
                    peak loads there can be longer wait time to get your jobs
                    from "pending" to "processing". If reducing waiting time is
                    your primary concern, then a combination of Pay-as-you-go
                    and Host-your-own-account option might suit you
                    better.Number of "pending" jobs counts as part of the
                    "concurrent jobs"
                - value: Failed
                  name: ''
                  description: Task failed. Check the error message for detail.
                - value: Staged
                  name: ''
                  description: >-
                    A stage only in Midjourney task . Means that you have
                    exceeded the number of your "concurrent jobs" limit and your
                    jobs are being queuedNumber of "staged" jobs does not count
                    as part of the "concurrent jobs". Also, please note the
                    maximum number of jobs in the "staged" queue is 50. So if
                    your operational needs exceed the 50 jobs limit, then please
                    create your own queuing system logic. 
              description: >-
                Hover on the "Completed" option and you coult see the
                explaintion of all status:
                completed/processing/pending/failed/staged
            input:
              type: object
              properties: {}
              x-apidog-orders: []
              x-apidog-ignore-properties: []
            output:
              type: object
              properties: {}
              x-apidog-orders: []
              x-apidog-ignore-properties: []
            meta:
              type: object
              properties:
                created_at:
                  type: string
                  description: >-
                    The time when the task was submitted to us (staged and/or
                    pending)
                started_at:
                  type: string
                  description: >-
                    The time when the task started processing. the time from
                    created_at to time of started_at is time the job spent in
                    the "staged“ stage and/or the"pending" stage if there were
                    any.
                ended_at:
                  type: string
                  description: The time when the task finished processing.
                usage:
                  type: object
                  properties:
                    type:
                      type: string
                    frozen:
                      type: number
                    consume:
                      type: number
                  x-apidog-orders:
                    - type
                    - frozen
                    - consume
                  required:
                    - type
                    - frozen
                    - consume
                  x-apidog-ignore-properties: []
                is_using_private_pool:
                  type: boolean
              x-apidog-orders:
                - created_at
                - started_at
                - ended_at
                - usage
                - is_using_private_pool
              required:
                - usage
                - is_using_private_pool
              x-apidog-ignore-properties: []
            detail:
              type: 'null'
            logs:
              type: array
              items:
                type: object
                properties: {}
                x-apidog-orders: []
                x-apidog-ignore-properties: []
            error:
              type: object
              properties:
                code:
                  type: integer
                message:
                  type: string
              x-apidog-orders:
                - code
                - message
              x-apidog-ignore-properties: []
          x-apidog-orders:
            - task_id
            - model
            - task_type
            - status
            - input
            - output
            - meta
            - detail
            - logs
            - error
          required:
            - task_id
            - model
            - task_type
            - status
            - input
            - output
            - meta
            - detail
            - logs
            - error
          x-apidog-ignore-properties: []
        message:
          type: string
          description: >-
            If you get non-null error message, here are some steps you chould
            follow:

            - Check our [common error
            message](https://climbing-adapter-afb.notion.site/Common-Error-Messages-6d108f5a8f644238b05ca50d47bbb0f4)

            - Retry for several times

            - If you have retried for more than 3 times and still not work, file
            a ticket on Discord and our support will be with you soon.
      x-examples:
        Example 1:
          code: 200
          data:
            task_id: 49638cd2-4689-4f33-9336-164a8f6b1111
            model: Qubico/flux1-dev
            task_type: txt2img
            status: pending
            input:
              prompt: a bear
            output: null
            meta:
              account_id: 0
              account_name: Qubico_test_user
              created_at: '2024-08-16T16:13:21.194049Z'
              started_at: ''
              completed_at: ''
            detail: null
            logs: []
            error:
              code: 0
              message: ''
          message: success
      x-apidog-orders:
        - code
        - data
        - message
      required:
        - code
        - data
        - message
      x-apidog-ignore-properties: []
      x-apidog-folder: ''
  securitySchemes: {}
servers:
  - url: https://api.piapi.ai
    description: Develop Env
security: []

```