# Application Router

``` json
"/graphs/all": {
      "get": {
        "summary": "Graphs",
        "description": "Return already crawled website graphs",
        "operationId": "graphs_graphs_all_get",
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {}
              }
            }
          }
        }
      }
    },
```
:   get all graph urls

``` json
"/graphs/": {
      "get": {
        "summary": "Graph Info",
        "description": "Return graph information, if present",
        "operationId": "graph_info_graphs__get",
        "parameters": [
          {
            "name": "url",
            "in": "query",
            "required": true,
            "schema": {
              "type": "string",
              "title": "Url"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/GraphInfo"
                }
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    }
```
:   get information about a graph 

``` json
"/queue-website/": {
      "post": {
        "summary": "Queue Website",
        "description": "Append website for crawling and return status",
        "operationId": "queue_website_queue_website__post",
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/QueueUrl"
              }
            }
          },
          "required": true
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {}
              }
            }
          },
          "422": {
            "description": "Validation Error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/HTTPValidationError"
                }
              }
            }
          }
        }
      }
    }
```