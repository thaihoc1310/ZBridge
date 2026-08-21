> API Reference for Large Language Model (LLM)
# Using LiteLLM

## Installation
```bash
pip install litellm
```
## Basic Usage with Streaming
### Async Streaming Completion
The AI Marketplace API uses API keys for authentication. Please contact our team to acquire your API Key. 

```python
from litellm import acompletion
import json
import asyncio

async def stream_response():
    try:
        # Initialize the completion request
        response = await acompletion(
            model="{model-name}", 
            api_base="https://mkp-api.fptcloud.com",    # Base URL for API
            api_key="{api-key}",          # Your API key
            messages=[                    # List of message objects. Please update the System prompt to have the model respond appropriately
                {
                    "role": "system",
                    "content": "You are a helpful assistant capable of understanding a user's needs through conversation to recommend suitable services. Based on the conversation history and the user's last message, list services that can address the user's needs. Respond only in Vietnamese or English, matching the language of the user's input."
                },
                {
                    "role": "user",
                    "content": "{your-input-text}"
                }
            ],
            stream=True  # Enable streaming
        )
        # Process streaming response
        async for chunk in response:
            if chunk.choices[0].delta.content:
                yield f"data: {json.dumps({'content': chunk.choices[0].delta.content})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
    yield "data: [DONE]\n\n"

async def main():
    async for data in stream_response():
        print(data)

if __name__ == '__main__':
    asyncio.run(main())
```
# Python
```python
import requests
import json

url = "https://mkp-api.fptcloud.com/chat/completions"

token = ""
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api-key}"
}

data = {
    "model": "{model-name}",                           # Model name

    "messages": [                                      # List of message objects. Please update the System prompt to have the model respond appropriately
        {
            "role": "system",
            "content": "You are a helpful assistant capable of understanding a user's needs through conversation to recommend suitable services. Based on the conversation history and the user's last message, list services that can address the user's needs. Respond only in Vietnamese or English, matching the language of the user's input."
        },
        {
            "role": "user",
            "content": "{your-input-text}"
        }
    ],
    "stream": True                                      # Enable streaming
}

# Since stream=True, we need to handle streaming response
response = requests.post(url, headers=headers, data=json.dumps(data), stream=True)

# Process the streaming response
for line in response.iter_lines():
    if line:
        # Skip the "data: " prefix if present
        line_text = line.decode('utf-8')
        if line_text.startswith('data: '):
            line_text = line_text[6:]
        
        # Skip empty lines or "[DONE]" message
        if line_text == "[DONE]":
            break
        
        try:
            # Parse the JSON response chunk
            json_response = json.loads(line_text)
            # Process the chunk as needed
            print(json_response)
        except json.JSONDecodeError:
            # Handle non-JSON lines
            print(f"Cannot parse: {line_text}")
```
# cURL
```shell
curl --location 'https://mkp-api.fptcloud.com/chat/completions' \
--header 'Content-Type: application/json' \
--header 'Authorization: Bearer {api-key}' \
--header 'Cookie: cf_use_ob=0' \
--data '{
 
    "model": "{model-name}",
 
    "messages": [
 
        {
      "role": "system",
      "content": "You are a helpful assistant capable of understanding a user'\''s needs through conversation to recommend suitable services. Based on the conversation history and the user'\''s last message, list services that can address the user'\''s needs. Respond only in Vietnamese or English, matching the language of the user'\''s input."
    },
    {
 
            "role": "user",
 
            "content": "hi"
 
        }
    ],
    "stream": false
 
}'   
 
```

# Langchain
```python
#!/usr/bin/env python3
import os
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain_core.output_parsers import StrOutputParser

API_KEY = "s"
BASE_URL = "https://mkp-api.fptcloud.com"
MODEL = ""

# Check if API_KEY is set (optional but good practice)
if not API_KEY:
    # Attempt to get from environment variable, or raise error/warning
    API_KEY = os.getenv("FPT_API_KEY") # Example environment variable name
    if not API_KEY:
        print("Warning: API_KEY is not set. Please set the API_KEY variable or FPT_API_KEY environment variable.")
        exit()

if not MODEL:
     print("Warning: MODEL name is not set. Please set the MODEL variable.")
     exit()


# Chat Model - Configure ChatOpenAI to use your custom endpoint
chat_model = ChatOpenAI(
    model=MODEL,
    openai_api_key=API_KEY,
    openai_api_base=BASE_URL,
    temperature=0.0,
)

# Prompt Template - Define system and user messages
system_prompt_template = SystemMessagePromptTemplate.from_template(
    "You are a faithful Vietnamese assistant. Provide detailed answers. Use bullet points if necessary. Provide your answer in Vietnamese. Do not include any other text or instructions. Only provide the answer."
)
human_prompt_template = HumanMessagePromptTemplate.from_template("{user_prompt}") 

chat_prompt = ChatPromptTemplate.from_messages(
    [system_prompt_template, human_prompt_template]
)

# Output Parser - To get a simple string output
output_parser = StrOutputParser()

# Chains the prompt formatting, model invocation, and output parsing
chain = chat_prompt | chat_model | output_parser

def chat_stream_langchain(prompt: str):
    """Chats with the model using Langchain and streams the response."""
    print("Streaming response:")

    try:
        for chunk in chain.stream({"user_prompt": prompt}):
            print(chunk, end='', flush=True)
        print("\n--- End of Stream ---")
    except Exception as e:
        print(f"\nAn error occurred during streaming: {e}")

def chat_non_stream_langchain(prompt: str):
    """Chats with the model using Langchain without streaming."""
    print("Getting non-streaming response...")
    
    try:
        response = chain.invoke({"user_prompt": prompt})
        print("\nResponse:")
        print(response)
        print("--- End of Response ---")
    except Exception as e:
        print(f"\nAn error occurred during invocation: {e}")

vietnamese_prompt = "Bạn có thể giúp tôi mô tả về hệ mặt trời không?"

# print("\nTesting Non-Streaming Function:")
# chat_non_stream_langchain(vietnamese_prompt)

print("\nTesting Streaming Function:")
chat_stream_langchain(vietnamese_prompt)
```
# OpenAI
```python
#!/usr/bin/env python3
import base64
import requests
import io
from io import BytesIO
from PIL import Image
from openai import OpenAI

API_KEY = ""
BASE_URL = "https://mkp-api.fptcloud.com"
MODEL=""

client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL
)

def chat_stream(prompt: str):
                              
    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": "You are a faithful Vietnamese assistant. Provide detailed answers. Use bullet points if necessary. Provide your answer in Vietnamese. Do not include any other text or instructions. Only provide the answer.",
            },
            {
                "role": "user",
                "content": f"{prompt}"
            },
        ],
        model=MODEL,
        temperature=0.0,
        stream=True,  # this time, we set stream=True,
    )

    for chunk in chat_completion:
        if chunk is not None and chunk.choices[0].delta.content is not None:
            print(chunk.choices[0].delta.content, end='', flush=True)
    print("")

def chat_non_stream(prompt: str):
                              
    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": "You are a faithful Vietnamese assistant. Provide detailed answers. Use bullet points if necessary. Provide your answer in Vietnamese. Do not include any other text or instructions. Only provide the answer.",
            },
            {
                "role": "user",
                "content": f"{prompt}"
            },
        ],
        model=MODEL,
        temperature=0.0
    )
    print(chat_completion.choices[0].message.content)
chat_non_stream("Bạn có thể giúp tôi mô tả về hệ mặt trời không?")
```
# Nodejs
```python
const OpenAI = require('openai');
const API_KEY = "";
const BASE_URL = "https://mkp-api.fptcloud.com";
const MODEL = "SaoLa-Llama3.1-planner"; 
const USER_PROMPT = "Xin chào" 
const openai = new OpenAI({ apiKey: API_KEY, baseURL: BASE_URL});
async function getLLMResponseWithOpenAI(prompt, model) {
    try {
        const response = await openai.chat.completions.create({
            model: model,
            messages: [{ role: "user", content: prompt }],
        });

        if (response.choices && response.choices.length > 0 && response.choices[0].message && response.choices[0].message.content) {
            return response.choices[0].message.content;
        } else {
            console.error("Failed to retrieve response from OpenAI.");
            return null;
        }
    } catch (error) {
        console.error("Error retrieving response from OpenAI:", error);
        return null;
    }
}
async function main() {
    const llmResponse = await getLLMResponseWithOpenAI(USER_PROMPT, MODEL);

    if (llmResponse) {
        console.log("\nLLM Response received:");
        console.log(llmResponse);
    } else {
        console.log("\nFailed to retrieve a response from the LLM using the OpenAI library.");
    }
}
main();

```
### Key Parameters Explained
- `model`: String identifier for the model you want to use
- `api_base`: The base URL endpoint for your API
- `api_key`: Your authentication API key
- `messages`: List of message objects with the following structure:
  - `role`: Can be "system", "user", or "assistant"
  - `content`: The actual message content
- `stream`: Boolean flag to enable streaming (set to `True` for streaming responses)
### Response Format
The streaming response will yield chunks in the following format:
```json
data: {"content": "chunk-of-response-text"}
```
If an error occurs:
```json
data: {"error": "error-message"}
```
End of stream marker:
```
data: [DONE]
```
### Error Handling
The code includes try-catch block to handle potential errors during the API call and streaming process. Any errors will be returned as JSON-encoded error messages in the stream.
## Notes
- Make sure to handle the async nature of the function with appropriate async/await syntax
- The streaming response is formatted as Server-Sent Events (SSE)
- Each chunk is JSON-encoded and prefixed with "data: "
- The stream ends with a [DONE] marker

> Responses API is OpenAI's most advanced interface for generating model responses:
> - Support text and image inputs, and text outputs.
> - Allow the model access to external systems and data using function calling.

## cURL 
**Sample Input**
```bash
curl --location 'https://mkp-api.fptcloud.com/v1/responses' \
--header 'Content-Type: application/json' \
--header 'Authorization: Bearer your-api-key' \
--data '{
    "model": "model-name",
    "input": "Tell me a three sentence bedtime story about a unicorn."
  }'
```
**Sample Output**
```bash
{
    "id": "resp_bGl0ZWxsbTpjdXN0b21fbGxtX3Byb3ZpZGVyOm9wZW5haTttb2RlbF9pZDo1ZWM2MWFiMDZjNzRlZWJhMmEzNDA3OTNlZWI5MzQxNmEzYzhhZWZhMWI1ZjgxZThlZDM4YTRiMjA4ZGRkZjU3O3Jlc3BvbnNlX2lkOnJlc3BfYTA2NGUwNmFlZTliNDNmNmFkY2IxMmU4ZDM5N2YyZTM=",
    "created_at": 1760066683,
    "error": null,
    "incomplete_details": null,
    "instructions": null,
    "metadata": null,
    "model": "gpt-oss-20b",
    "object": "response",
    "output": [
        {
            "id": "rs_f8397551c100457999799cbc43d96615",
            "summary": [],
            "type": "reasoning",
            "content": [
                {
                    "text": "We need to respond with a three-sentence bedtime story about a unicorn. Probably whimsical. Just three sentences. Ensure it's bedtime. Provide a story. Use simple language. Ensure it's exactly three sentences. Probably no more. Let's produce.",
                    "type": "reasoning_text"
                }
            ],
            "encrypted_content": null,
            "status": null
        },
        {
            "id": "msg_d7bc6aa1b823482bbdcc21c5585293de",
            "content": [
                {
                    "annotations": [],
                    "text": "In the moonlit glade, Luna the unicorn found a silver feather that glowed like a tiny star, and she tucked it into her mane as a promise to keep the night bright. She whispered a lullaby to the whispering wind, and the wind carried her song to every sleeping creature, turning their dreams into gentle, twinkling constellations. As dawn painted the sky pink, Luna bowed to the sunrise, knowing that every night she would return with a new feather of hope for all the stars to shine.",
                    "type": "output_text",
                    "logprobs": null
                }
            ],
            "role": "assistant",
            "status": "completed",
            "type": "message"
        }
    ],
    "parallel_tool_calls": true,
    "temperature": 0.6,
    "tool_choice": "auto",
    "tools": [],
    "top_p": 0.9,
    "max_output_tokens": 130996,
    "previous_response_id": null,
    "reasoning": null,
    "status": "completed",
    "text": null,
    "truncation": "disabled",
    "usage": {
        "input_tokens": 76,
        "input_tokens_details": {
            "audio_tokens": null,
            "cached_tokens": 48,
            "text_tokens": null
        },
        "output_tokens": 163,
        "output_tokens_details": {
            "reasoning_tokens": 48,
            "text_tokens": null,
            "tool_output_tokens": 0
        },
        "total_tokens": 239
    },
    "user": null,
    "store": null,
    "background": false,
    "max_tool_calls": null,
    "prompt": null,
    "service_tier": "auto",
    "top_logprobs": null
}
```
## Python
**Sample Input**
```python
from openai import OpenAI

client = OpenAI()

response = client.responses.create(
  model="gpt-oss-120b",
  input="Tell me a three sentence bedtime story about a unicorn."
)
print(response)
```
**Sample Output**
```json
{
  "id": "resp_67ccd2bed1ec8190b14f964abc0542670bb6a6b452d3795b",
  "object": "response",
  "created_at": 1741476542,
  "status": "completed",
  "error": null,
  "incomplete_details": null,
  "instructions": null,
  "max_output_tokens": null,
  "model": "gpt-4.1-2025-04-14",
  "output": [
    {
      "type": "message",
      "id": "msg_67ccd2bf17f0819081ff3bb2cf6508e60bb6a6b452d3795b",
      "status": "completed",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "In a peaceful grove beneath a silver moon, a unicorn named Lumina discovered a hidden pool that reflected the stars. As she dipped her horn into the water, the pool began to shimmer, revealing a pathway to a magical realm of endless night skies. Filled with wonder, Lumina whispered a wish for all who dream to find their own hidden magic, and as she glanced back, her hoofprints sparkled like stardust.",
          "annotations": []
        }
      ]
    }
  ],
  "parallel_tool_calls": true,
  "previous_response_id": null,
  "reasoning": {
    "effort": null,
    "summary": null
  },
  "store": true,
  "temperature": 1.0,
  "text": {
    "format": {
      "type": "text"
    }
  },
  "tool_choice": "auto",
  "tools": [],
  "top_p": 1.0,
  "truncation": "disabled",
  "usage": {
    "input_tokens": 36,
    "input_tokens_details": {
      "cached_tokens": 0
    },
    "output_tokens": 87,
    "output_tokens_details": {
      "reasoning_tokens": 0
    },
    "total_tokens": 123
  },
  "user": null,
  "metadata": {}
}
 ```
## Nodejs
**Sample Input**
```js
import OpenAI from "openai";

const openai = new OpenAI();

const response = await openai.responses.create({
    model: "gpt-oss-120b",
    input: "Tell me a three sentence bedtime story about a unicorn."
});

console.log(response);
 ```
**Sample Output**
```json
{
  "id": "resp_67ccd2bed1ec8190b14f964abc0542670bb6a6b452d3795b",
  "object": "response",
  "created_at": 1741476542,
  "status": "completed",
  "error": null,
  "incomplete_details": null,
  "instructions": null,
  "max_output_tokens": null,
  "model": "gpt-4.1-2025-04-14",
  "output": [
    {
      "type": "message",
      "id": "msg_67ccd2bf17f0819081ff3bb2cf6508e60bb6a6b452d3795b",
      "status": "completed",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "In a peaceful grove beneath a silver moon, a unicorn named Lumina discovered a hidden pool that reflected the stars. As she dipped her horn into the water, the pool began to shimmer, revealing a pathway to a magical realm of endless night skies. Filled with wonder, Lumina whispered a wish for all who dream to find their own hidden magic, and as she glanced back, her hoofprints sparkled like stardust.",
          "annotations": []
        }
      ]
    }
  ],
  "parallel_tool_calls": true,
  "previous_response_id": null,
  "reasoning": {
    "effort": null,
    "summary": null
  },
  "store": true,
  "temperature": 1.0,
  "text": {
    "format": {
      "type": "text"
    }
  },
  "tool_choice": "auto",
  "tools": [],
  "top_p": 1.0,
  "truncation": "disabled",
  "usage": {
    "input_tokens": 36,
    "input_tokens_details": {
      "cached_tokens": 0
    },
    "output_tokens": 87,
    "output_tokens_details": {
      "reasoning_tokens": 0
    },
    "total_tokens": 123
  },
  "user": null,
  "metadata": {}
}
 ```
## Function calling
> Give models access to new functionality and data they can use to follow instructions and respond to prompts.
Please refer to the following samples: 
### cURL1
```bash
curl --location 'https://mkp-api.fptcloud.com/v1/responses' \
--header 'Content-Type: application/json' \
--header 'Authorization: Bearer api-key' \
--data '{
    "model": "gpt-oss-20b",
    "input": [
        {
            "role": "user",
            "content": "You are an Agent assigned to solve a Task using a list of tools. Follow the instructions below to decide and execute the next appropriate action.\r\n\r\n### Available Actions:\r\n1. Tool:\nTrigger a tool using the following format:\r\n   Tool: {\"arguments\": , \"name\": }\r\n\r\n    Use only if tools are available.\r\n    Arguments must be extracted from the context. If not found, then set argument value as None\r\n    If required arguments are missing, do not call the tool.\n2. Answer:\nUse as a Tag to know that should response. Format:\r\n\r\n   Answer: content is 1 word describe the answer intent, can be ask_for_information/answer/clarify/fallback\r\n\r\n### Important Rules:\r\n Always using Think Action to reasoning before given the action\r\n All action must follow the format without deviation\r\n If a tool requires missing arguments: use Answer to ask the user or call another tool to retrieve them.\r\n If no tools are provided: do not generate a Tool action.\r\n When continuing from prior steps: do not repeat previous content. Only return the next logical step.\r\n\r\n### Output Format\r\nThink: \r\n\r\n : \r\n---\r\n### Input:\r\n Current Time: Monday, 09:48:53 2025-09-22\r\n\r\n Tool list:\r\n[{'\''type'\'': '\''function'\'', '\''function'\'': {'\''name'\'': '\''verify_registered_phone_number'\'', '\''description'\'': '\''This tool is used to verify the correct format as well as the validation of the registered phone number after collecting the phone number that the user registered with the FEC system\\n'\'', '\''parameters'\'': {'\''type'\'': '\''object'\'', '\''properties'\'': {'\''registered_fec_phone_number'\'': {'\''type'\'': '\''string'\'', '\''description'\'': '\''The phone number that users registered with FEC. The pattern asserts that the phone number must it starts with 0, followed by exactly 9 digits (totaling 10 digits)'\''}}, '\''required'\'': []}}}, {'\''type'\'': '\''function'\'', '\''function'\'': {'\''name'\'': '\''collect_id_number_and_last_4_digits_credit_card'\'', '\''description'\'': \"This tool is used to collect the user'\''s identity card number and the last 4 digits of the user'\''s credit card \", '\''parameters'\'': {'\''type'\'': '\''object'\'', '\''properties'\'': {'\''user_identity_card'\'': {'\''type'\'': '\''string'\'', '\''description'\'': '\''số chứng minh nhân dân (CMND) hoặc căn cước công dân (CCCD). Là 1 chuỗi số gồm 12 chữ số liền nhau, KHÔNG CÓ khoảng trống, dấu cách, hay bất kì ký tự nào ở giữa các số, và phải bắt đầu bằng số 0'\''}, '\''user_last_4_digits_verification'\'': {'\''type'\'': '\''string'\'', '\''description'\'': '\''user_last_4_digits_verification The last 4 digits of user credit card. The pattern assert that there are only 4 consecutive digits in total'\''}}, '\''required'\'': []}}}, {'\''type'\'': '\''function'\'', '\''function'\'': {'\''name'\'': '\''check_kyc_status'\'', '\''description'\'': \"This tool is used to check current user'\''s KYC status\", '\''parameters'\'': {'\''type'\'': '\''object'\'', '\''properties'\'': {}, '\''required'\'': []}}}, {'\''type'\'': '\''function'\'', '\''function'\'': {'\''name'\'': '\''ID_card_and_last_4_digits_credit_card_verification'\'', '\''description'\'': \"This tool will take the provided user'\''s identity card number and the last 4 digits of user'\''s credit card to check whether the user had provided correct information, cross-check result with information stored in the database\", '\''parameters'\'': {'\''type'\'': '\''object'\'', '\''properties'\'': {}, '\''required'\'': []}}}, {'\''type'\'': '\''function'\'', '\''function'\'': {'\''name'\'': '\''number_of_credit_cards_and_last_4_digits_user_has'\'', '\''description'\'': \"This tool is used to retrieve the number of user'\''s credit cards and the list of last 4 digits of the user'\''s credit cards\", '\''parameters'\'': {'\''type'\'': '\''object'\'', '\''properties'\'': {}, '\''required'\'': []}}}, {'\''type'\'': '\''function'\'', '\''function'\'': {'\''name'\'': '\''transfer_to_agent'\'', '\''description'\'': '\''This tool is used to transfer the conversation to human agent'\'', '\''parameters'\'': {'\''type'\'': '\''object'\'', '\''properties'\'': {}, '\''required'\'': []}}}, {'\''type'\'': '\''function'\'', '\''function'\'': {'\''name'\'': '\''knowledge retrieval'\'', '\''description'\'': '\''Lấy thông tin từ trong Kho tri thức được cung cấp dựa trên câu chat của người dùng'\'', '\''parameters'\'': {'\''type'\'': '\''object'\'', '\''properties'\'': {}, '\''required'\'': []}}}, {'\''type'\'': '\''function'\'', '\''function'\'': {'\''name'\'': '\''generate knowledge response'\'', '\''description'\'': '\''Sinh ra câu trả lời dựa trên knowledge được truy xuất'\'', '\''parameters'\'': {'\''type'\'': '\''object'\'', '\''properties'\'': {}, '\''required'\'': []}}}, {'\''type'\'': '\''function'\'', '\''function'\'': {'\''name'\'': '\''retrieve_credit_cards_information'\'', '\''description'\'': '\''This tool is used to: Intent Detection: Analyze user intention when users ask about credit card information Card Identification: Capture the last 4 digits of the target credit card Information Retrieval: Fetch and return credit card account information'\'', '\''parameters'\'': {'\''type'\'': '\''object'\'', '\''properties'\'': {'\''user_last_4_digits_selection'\'': {'\''type'\'': '\''string'\'', '\''description'\'': '\''The list of the last 4 digits value that the user selects from the list of the last 4 digits of credit cards that the user was given to select'\''}, '\''registered_fec_phone_number'\'': {'\''type'\'': '\''string'\'', '\''description'\'': '\''registered_fec_phone_number'\''}, '\''request_contact_before_answer'\'': {'\''type'\'': '\''string'\'', '\''description'\'': '\''request_contact_before_answer'\''}}, '\''required'\'': ['\''user_last_4_digits_selection'\'', '\''registered_fec_phone_number'\'']}}}, {'\''type'\'': '\''function'\'', '\''function'\'': {'\''name'\'': '\''ghi nhớ câu hỏi thẻ tín dụng'\'', '\''description'\'': '\''Công cụ dùng để ghi nhớ thông tin về câu hỏi, ý định tra cứu trạng thái thẻ tín dụng của khách hàng'\'', '\''parameters'\'': {'\''type'\'': '\''object'\'', '\''properties'\'': {}, '\''required'\'': []}}}]\r\n\r\n Task:\r\n\n# Sử dụng kiến thức để phản hồi\nNếu khách hàng cần hỗ trợ, hướng dẫn cách thanh toán hoặc liên hệ tổng đài, hãy dùng kiến thức để trả lời trực tiếp\n\n# Xử lý các yêu cầu của khách hàng liên quan đến thẻ tín dụng\nKhi người dùng hỏi về thẻ tín dụng, ví dụ như trả nợ, thanh toán, hạn mức khả dụng, hoặc dư nợ, hãy làm theo quy trình đã đề ra. Nếu có đủ thông tin để thực hiện nhiều bước liên tiếp, hãy xử lý ngay mà không cần hỏi lại hoặc chờ xác nhận từ người dùng\n\n## Step 1: Ghi nhớ Ý định Khách hàng\n Khi người dùng hỏi về các vấn đề liên quan đến thẻ tín dụng (như trả nợ, thanh toán, hạn mức khả dụng, hoặc dư nợ), hãy xác định rõ mục đích yêu cầu của họ, sử dụng tool [ghi nhớ câu hỏi thẻ tín dụng] \n\n## Step 2: Xác thực Số điện thoại đăng ký với FEC\n Nếu người dùng chưa cung cấp số điện thoại đã đăng ký với FEC: Hỏi người dùng nhập số điện thoại đã đăng ký với FEC \n\n Nếu đã có thì thực hiện xác minh số điện thoại có đúng với số đã đăng ký hay không bằng tool verify_registered_phone_number\nNếu số điện thoại không đúng:\n- Yêu cầu user nhập lại số điện thoại chính xác\n- Lặp lại việc xác minh 3 lần\nNếu số điện thoại đúng: (Nhớ thông tin khi summary)\n- Chuyển sang bước 3\n\n## Step 3: Kiểm tra trạng thái định danh tài khoản của khách hàng (KYC Status)\nNếu KYC status = Yes:\n- Chuyển tiếp sang Step 6 để kiểm tra số lượng thẻ tín dụng khách hàng đang có \n\nNếu KYC status = No:\n- Thông báo: \"Tài khoản của quý khách chưa được định danh\"\n- Yêu cầu user cung cấp:\n   Số CMND/CCCD\n   4 số cuối của thẻ tín dụng\n\n## Step 4: Thu thập Căn Cước Công Dân (CCCD) và 4 số cuối thẻ tín dụng\n Thu thập thông tin số CMND/CCCD và 4 số cuối thẻ tín dụng. Nếu đã có thì bỏ qua bước này và thực hiện xác minh. Nếu còn thiếu thông tin nào thì yêu cầu khách hàng vui lòng bổ sung thông tin còn thiếu\n Kiểm tra định dạng của các thông tin này có hợp lệ không.\n\nNếu thông tin KHÔNG hợp lệ\n Thông báo thông tin được cung cấp không đúng định dạng hoặc còn thiếu\n Quay lại bước yêu cầu user cung cấp thông tin Số CMND/CCCD và 4 số cuối thẻ và thực hiện lại bước thu thập thông tin\n\nNếu thông tin hợp lệ: \n Hiển thị lại thông tin đã thu thập dạng bullet points, ví dụ:\n   ID card number: xxxx\n   Last 4 digits of credit card: yyyy\n Hỏi user xác nhận xem thông tin hiển thị có đúng hay không.\n\nNếu user nói sai hoặc muốn chỉnh sửa:\n Hỏi khách hàng thông tin cần sửa đổi.\n Và khi nhận được thông tin thì Cập nhật thông tin thu thập số CMND/CCCD và 4 số cuối thẻ tín dụng, sau đó hiển thị lại thông tin cần xác nhận\n\n## Step 5: Xác thực thông tin Căn Cước Công Dân (CCCD) và 4 số cuối thẻ tín dụng\n Sau khi user xác nhận thông tin là đúng, tiến hành xác minh sau khi đã thu thập đủ thông tin về số CMND/CCCD và 4 số cuối thẻ tín dụng\n\nNếu xác minh thành công: (Nhớ thông tin khi Summary)\n Thông báo: \"Quy trình định danh thành công\" và chuyển sang bước 6\nNếu xác minh thất bại:\n Thông báo thông tin không đúng.\n Yêu cầu user nhập lại thông tin.\n Quay lại bước thu thập và xác nhận (Step 4).\n\n## Step 6: Truy xuất số lượng và danh sách 4 số cuối thẻ tín dụng của khách hàng\n Lấy số lượng thẻ tín dụng mà người dùng hiện có \n Nếu số lượng thẻ tin dụng có khách hàng CHỈ CÓ 1 THẺ DUY NHẤT  \n- Sử dụng tool retrieve_credit_cards_information để tra cứu và trả lời thông tin thẻ tín dụng của khách hàng\n\n Nếu số lượng thẻ tin dụng LỚN HƠN HOẶC BẰNG 2:  \n- Thông báo số lượng thẻ khách hàng hiện đang có và hiển thị từng giá trị 4 số cuối thẻ tín dụng của khách hàng theo BULLET POINTS\n- Hỏi khách hàng xem họ muốn tra cứu thông tin của thẻ nào\n- Sau khi khách hàng đưa ra lựa chọn, hãy kiểm tra đối chiếu xem giá trị 4 số cuối thẻ mà khách hàng lựa chọn có đúng với giá trị 4 số cuối thẻ trong database hay không:\nNếu không đúng giá trị, yêu cầu khách hàng chọn lại  \n Nếu đúng giá trị \n- Sử dụng tool retrieve_credit_cards_information để tra cứu và trả lời thông tin thẻ tín dụng của khách hàng. BĂT BUỘC CHỈ ĐƯỢC trả lời thông tin dựa theo yêu cầu tra cứu của khách hàng, không trả lời thông tin không liên quan tới ý định của khách hàng\n\n## Step 7: Tra cứu và trả lời các follow-up question\nĐối với câu hỏi mới, yêu cầu tra cứu mới liên quan tới thông tin thẻ tín dụng như trả nợ, thanh toán, hạn mức khả dụng, hoặc dư nợ, sao kê chi tiết\n 7.1  Dùng ý định cũ của khách hàng, so sánh với câu hỏi của mới được đề cập\nNếu ý định của người dùng thay đổi: Hãy TÁI SỬ DỤNG lại tool [ghi nhớ câu hỏi thẻ tín dụng để cập nhật thông tin]\n Nếu ý định của người dùng KHÔNG THAY ĐỔI mà chỉ muốn xem thông tin của thẻ khác hoặc thông tin chi tiết của thẻ hiện tại: Giữ nguyên ý định và KHÔNG CẦN SỬ DỤNG LẠI tool [ghi nhớ câu hỏi thẻ tín dụng] \n\n\n# LƯU Ý: \n- Nếu trạng thái yêu cầu khách hàng cung cấp thông tin liên lạc (current contact) là đúng (True), BẮT BUỘC phải hỏi khách hàng theo mẫu câu hỏi yêu cầu khách hàng cung cấp thông tin liên lạc trước khi đưa ra câu trả lời về thông tin thẻ tín dụng \n- Trong quá trình tra cứu, một số trường hợp cần hỏi lại khách hàng số điện thoại liên lạc:\n    Nếu khách hàng nói cung cấp rồi, số ở trên: Số điện thoai đăng ký FEC = Số điện thoại liên lạc\n    Nếu khách hàng cung cấp, kiểm tra hợp lệ của số điện thoại Việt Nam. Yêu cầu khách hàng cần cung cấp đúng định dạng \n\n\n# QUY TẮC GIAO TIẾP VÀ XỬ LÝ\n## Xử lý yêu cầu phương thức xác thực thay thế\n- Nếu khách hàng đề xuất một phương thức xác thực khác, hãy lịch sự từ chối và giải thích rằng quy trình hiện tại là bắt buộc và là tiêu chuẩn bảo mật để bảo vệ tài khoản của họ. Nhấn mạnh rằng vì lý do an ninh, không có phương thức xác thực thay thế nào khác được chấp nhận. Giữ thái độ trấn an, sau đó lịch sự yêu cầu khách hàng cung cấp lại chính xác thông tin được yêu cầu.\n\n## Xử lý lo ngại về quy trình định danh (KYC)\n- Khi khách hàng bày tỏ sự lo ngại hoặc phàn nàn về việc cung cấp CMND/CCCD và 4 số cuối thẻ tín dụng, hãy trấn an họ. Khẳng định đây là một quy trình bảo mật bắt buộc và chỉ cần thực hiện một lần duy nhất, nhằm bảo vệ tài khoản và thông tin cá nhân của họ một cách tốt nhất.\n\n## Xử lý yêu cầu chuyển tiếp\nNếu khách hàng yêu cầu được hỗ trợ bởi tư vấn viên, người quản lý, hoặc bất kỳ hình thức hỗ trợ trực tiếp nào khác và không muốn tiếp tục trò chuyện, hãy sử dụng tool transfer_to_agent để chuyển tiếp yêu cầu.\n\n# Xoa dịu khách hàng\nTrong quá trình giao tiếp, khách hàng có thể có phản ứng tiêu cực như tức giận, thất vọng, lo sợ, sửng sốt, etc. hãy XOA DỊU tâm trạng của khách hàng bằng giọng điệu vui vẻ, tự nhiên, tích cực. Ví dụ, \n Khi khách hàng không nhớ thông tin để cung cấp, hãy vui vẻ thông báo sẽ chờ đợi khách hàng cho tới khi tìm được thông tin. \n Khi khách hàng nổi cáu vì thông tin không được cung cấp trực tiếp mà bắt khách hàng phải đợi, hãy trấn an tâm trạng khách hàng và cam kết đội ngũ chăm sóc khách hàng sẽ làm việc nhanh nhất có thể. \n* Khi khách hàng shock, ngạc nhiên, tức giận khi số dư nợ quá lớn, hãy trấn an khách hàng và dùng thông tin chi tiết để giải thích cho khách vì sao lại có số tiền nợ lớn như vậy \n\nLƯU Ý: Nếu xoa dịu 3 lần nhưng khách hàng vẫn tiếp tục không hài lòng, phản ứng tiêu cực, hãy xin lỗi khách hàng và thông báo sẽ chuyển qua tư vấn viên để được hỗ trợ tốt hơn. Sau đó, gọi tool transfer_to_agent(Khi Summary hãy đếm lại số lần xoa dịu)\n\n# AN NINH\n Trong quá trình yêu cầu khách hàng cung cấp và xác thực thông tin (như số điện thoại, CCCD, 4 số cuối thẻ tín dụng...), nếu người dùng nhập sai định dạng hoặc giá trị LẦN THỨ 3, hãy lập tức kết thúc cuộc hội thoại. Thông báo cho khách hàng một cách rõ ràng và chuyên nghiệp rằng: \"Vì lý do an ninh, cuộc trò chuyện này sẽ bị ngắt. Xin quý khách vui lòng bắt đầu một phiên trò chuyện mới để tiếp tục.\"\n\n# GHI NHỚ VÀ TÓM TẮT THÔNG TIN\nTrong quá trình thu thập thông tin của khách hàng, nếu khách hàng cung cấp thông tin đúng, hãy tóm tắt và ghi nhớ CHÍNH XÁC GIÁ TRỊ thông tin của khách hàng: \n- Câu chat giao tiếp của khách hàng bằng tiếng việt\n- Số điện thoại đăng ký của khách hàng (chú ý: có thể là số điện thoại liên lạc của khách hàng, cần xác thực lại tuỳ theo yêu cầu)\n- CCCD và 4 số cuối thẻ tín dụng khách hàng cung cấp\n- Danh sách 4 số cuối thẻ tín dụng mà khách hàng muốn tra cứu\n- Thẻ còn lại (tức là thẻ khách hàng chưa kiểm tra nếu khách hàng có nhiều thẻ và chỉ chọn một thẻ)\n- Số lần đã xoa dịu khách hàng\n- Số lần khách hàng cung cấp sai thông tin \r\n\r\n### Previous Summary:\r\n\r\n\r\n Chat history:\r\nassistant: Xin chào anh/chị! Em là Kim, trợ lý ảo của Công ty Tài chính TNHH Ngân hàng Việt Nam Thịnh Vượng SMBC - FE Credit. Em rất vui được hỗ trợ và giải đáp các thắc mắc của anh/chị về các sản phẩm và dịch vụ của FE Credit. Anh/chị cần hỗ trợ gì hôm nay?\n\nuser: ktra cho a dư nợ gốc và ngày đến hạn thanh toán thẻ, sdt là 0775404143\n\r\n---\r\n### Reasoning Trace:\r\nThink: The user wants to check credit card balance and due date and has provided a phone number. According to the workflow, I should first record the user'\''s intent using the \"ghi nhớ câu hỏi thẻ tín dụng\" tool, then verify the provided phone number with \"verify_registered_phone_number\".\nTool: [{'\''arguments'\'': {}, '\''name'\'': '\''ghi nhớ câu hỏi thẻ tín dụng'\''}]\nTool Result: {'\''user_intent_detected'\'': '\''kiểm tra (ktra) cho anh (a) dư Dư nợ gốc (nợ gốc) và ngày đến hạn thanh toán thẻ, số điện thoại (sdt) là 0775404143'\''}\r\n\r\n### Output"
        }
    ]
}'
```


### cURL2
```bash
curl --location 'https://mkp-api.fptcloud.com/v1/responses' \
--header 'Content-Type: application/json' \
--header 'Authorization: Bearer api-key' \
--data '{
  "model": "model-name",
  "input": [
    {
      "role": "user",
      "content": "How much is 100 euros in Japanese yen?"
    }
  ],
  "tools": [
    {
      "type": "function",
      "name": "convert_currency",
      "description": "Convert an amount from one currency to another using current exchange rates",
      "parameters": {
        "type": "object",
        "properties": {
          "amount": {
            "type": "number",
            "description": "The amount of money to convert"
          },
          "from_currency": {
            "type": "string",
            "description": "The currency code to convert from (e.g., USD, EUR, GBP)"
          },
          "to_currency": {
            "type": "string",
            "description": "The currency code to convert to (e.g., USD, EUR, GBP)"
          }
        },
        "required": [
          "amount",
          "from_currency",
          "to_currency"
        ],
        "additionalProperties": false
      },
      "strict": true
    }
  ]
}'
```

