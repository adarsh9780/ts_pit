/* eslint-disable */
/* tslint:disable */
// @ts-nocheck
/*
 * ---------------------------------------------------------------
 * ## THIS FILE WAS GENERATED VIA SWAGGER-TYPESCRIPT-API        ##
 * ##                                                           ##
 * ## AUTHOR: acacode                                           ##
 * ## SOURCE: https://github.com/acacode/swagger-typescript-api ##
 * ---------------------------------------------------------------
 */

import axios from "axios";
export var ContentType;
(function (ContentType) {
  ContentType["Json"] = "application/json";
  ContentType["JsonApi"] = "application/vnd.api+json";
  ContentType["FormData"] = "multipart/form-data";
  ContentType["UrlEncoded"] = "application/x-www-form-urlencoded";
  ContentType["Text"] = "text/plain";
})(ContentType || (ContentType = {}));
export class HttpClient {
  instance;
  securityData = null;
  securityWorker;
  secure;
  format;
  constructor({ securityWorker, secure, format, ...axiosConfig } = {}) {
    this.instance = axios.create({
      ...axiosConfig,
      baseURL: axiosConfig.baseURL || "",
    });
    this.secure = secure;
    this.format = format;
    this.securityWorker = securityWorker;
  }
  setSecurityData = (data) => {
    this.securityData = data;
  };
  mergeRequestParams(params1, params2) {
    const method = params1.method || (params2 && params2.method);
    return {
      ...this.instance.defaults,
      ...params1,
      ...(params2 || {}),
      headers: {
        ...((method && this.instance.defaults.headers[method.toLowerCase()]) ||
          {}),
        ...(params1.headers || {}),
        ...((params2 && params2.headers) || {}),
      },
    };
  }
  stringifyFormItem(formItem) {
    if (typeof formItem === "object" && formItem !== null) {
      return JSON.stringify(formItem);
    } else {
      return `${formItem}`;
    }
  }
  createFormData(input) {
    if (input instanceof FormData) {
      return input;
    }
    return Object.keys(input || {}).reduce((formData, key) => {
      const property = input[key];
      const propertyContent = property instanceof Array ? property : [property];
      for (const formItem of propertyContent) {
        const isFileType = formItem instanceof Blob || formItem instanceof File;
        formData.append(
          key,
          isFileType ? formItem : this.stringifyFormItem(formItem),
        );
      }
      return formData;
    }, new FormData());
  }
  request = async ({ secure, path, type, query, format, body, ...params }) => {
    const secureParams =
      ((typeof secure === "boolean" ? secure : this.secure) &&
        this.securityWorker &&
        (await this.securityWorker(this.securityData))) ||
      {};
    const requestParams = this.mergeRequestParams(params, secureParams);
    const responseFormat = format || this.format || undefined;
    if (
      type === ContentType.FormData &&
      body &&
      body !== null &&
      typeof body === "object"
    ) {
      body = this.createFormData(body);
    }
    if (
      type === ContentType.Text &&
      body &&
      body !== null &&
      typeof body !== "string"
    ) {
      body = JSON.stringify(body);
    }
    return this.instance.request({
      ...requestParams,
      headers: {
        ...(requestParams.headers || {}),
        ...(type ? { "Content-Type": type } : {}),
      },
      params: query,
      responseType: responseFormat,
      data: body,
      url: path,
    });
  };
}
/**
 * @title FastAPI
 * @version 0.1.0
 */
export class Api extends HttpClient {
  ui = {
    /**
     * @description Serve the frontend SPA. All routes fall back to index.html for client-side routing.
     *
     * @name ServeFrontendUiPathGet
     * @summary Serve Frontend
     * @request GET:/ui/{path}
     */
    serveFrontendUiPathGet: (path, params = {}) =>
      this.request({
        path: `/ui/${path}`,
        method: "GET",
        format: "json",
        ...params,
      }),
    /**
     * @description Serve the frontend SPA. All routes fall back to index.html for client-side routing.
     *
     * @name ServeFrontendUiGet
     * @summary Serve Frontend
     * @request GET:/ui
     */
    serveFrontendUiGet: (query, params = {}) =>
      this.request({
        path: `/ui`,
        method: "GET",
        query: query,
        format: "json",
        ...params,
      }),
  };
  articles = {
    /**
     * @description Generate AI analysis for a specific article using its price impact context.
     *
     * @name AnalyzeArticleArticlesIdAnalyzePost
     * @summary Analyze Article
     * @request POST:/articles/{id}/analyze
     */
    analyzeArticleArticlesIdAnalyzePost: (id, params = {}) =>
      this.request({
        path: `/articles/${id}/analyze`,
        method: "POST",
        format: "json",
        ...params,
      }),
  };
  config = {
    /**
     * @description Return configuration for the frontend.
     *
     * @name GetConfigEndpointConfigGet
     * @summary Get Config Endpoint
     * @request GET:/config
     */
    getConfigEndpointConfigGet: (params = {}) =>
      this.request({
        path: `/config`,
        method: "GET",
        format: "json",
        ...params,
      }),
  };
  mappings = {
    /**
     * @description Legacy endpoint - returns same as /config.
     *
     * @name GetMappingsMappingsGet
     * @summary Get Mappings
     * @request GET:/mappings
     */
    getMappingsMappingsGet: (params = {}) =>
      this.request({
        path: `/mappings`,
        method: "GET",
        format: "json",
        ...params,
      }),
  };
  alerts = {
    /**
     * @description Get all alerts, optionally filtered by date.
     *
     * @name GetAlertsAlertsGet
     * @summary Get Alerts
     * @request GET:/alerts
     */
    getAlertsAlertsGet: (query, params = {}) =>
      this.request({
        path: `/alerts`,
        method: "GET",
        query: query,
        format: "json",
        ...params,
      }),
    /**
     * @description Update the status of an alert.
     *
     * @name UpdateAlertStatusAlertsAlertIdStatusPatch
     * @summary Update Alert Status
     * @request PATCH:/alerts/{alert_id}/status
     */
    updateAlertStatusAlertsAlertIdStatusPatch: (alertId, data, params = {}) =>
      this.request({
        path: `/alerts/${alertId}/status`,
        method: "PATCH",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),
    /**
     * @description Get details for a specific alert.
     *
     * @name GetAlertDetailAlertsAlertIdGet
     * @summary Get Alert Detail
     * @request GET:/alerts/{alert_id}
     */
    getAlertDetailAlertsAlertIdGet: (alertId, params = {}) =>
      this.request({
        path: `/alerts/${alertId}`,
        method: "GET",
        format: "json",
        ...params,
      }),
    /**
     * @description Generate AI summary for the alert.
     *
     * @name GenerateSummaryAlertsAlertIdSummaryPost
     * @summary Generate Summary
     * @request POST:/alerts/{alert_id}/summary
     */
    generateSummaryAlertsAlertIdSummaryPost: (alertId, params = {}) =>
      this.request({
        path: `/alerts/${alertId}/summary`,
        method: "POST",
        format: "json",
        ...params,
      }),
    /**
     * @description Generate a downloadable investigation report for an alert. Stored under artifacts/reports/{session_id}/{alert_id}_{timestamp}.html
     *
     * @name GenerateAlertReportAlertsAlertIdReportPost
     * @summary Generate Alert Report
     * @request POST:/alerts/{alert_id}/report
     */
    generateAlertReportAlertsAlertIdReportPost: (alertId, data, params = {}) =>
      this.request({
        path: `/alerts/${alertId}/report`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),
  };
  prices = {
    /**
     * @description Get price data for a ticker with industry comparison.
     *
     * @name GetPricesPricesTickerGet
     * @summary Get Prices
     * @request GET:/prices/{ticker}
     */
    getPricesPricesTickerGet: (ticker, query, params = {}) =>
      this.request({
        path: `/prices/${ticker}`,
        method: "GET",
        query: query,
        format: "json",
        ...params,
      }),
  };
  news = {
    /**
     * @description Get news articles for an ISIN.
     *
     * @name GetNewsNewsIsinGet
     * @summary Get News
     * @request GET:/news/{isin}
     */
    getNewsNewsIsinGet: (isin, query, params = {}) =>
      this.request({
        path: `/news/${isin}`,
        method: "GET",
        query: query,
        format: "json",
        ...params,
      }),
  };
  agent = {
    /**
     * @description Retrieve chat history for a given session from the LangGraph checkpointer. Returns messages in a format suitable for the frontend.
     *
     * @name GetChatHistoryAgentHistorySessionIdGet
     * @summary Get Chat History
     * @request GET:/agent/history/{session_id}
     */
    getChatHistoryAgentHistorySessionIdGet: (sessionId, params = {}) =>
      this.request({
        path: `/agent/history/${sessionId}`,
        method: "GET",
        format: "json",
        ...params,
      }),
    /**
     * @description Delete chat history for a given session from the LangGraph checkpointer.
     *
     * @name DeleteChatHistoryAgentHistorySessionIdDelete
     * @summary Delete Chat History
     * @request DELETE:/agent/history/{session_id}
     */
    deleteChatHistoryAgentHistorySessionIdDelete: (sessionId, params = {}) =>
      this.request({
        path: `/agent/history/${sessionId}`,
        method: "DELETE",
        format: "json",
        ...params,
      }),
    /**
     * @description Chat with the Trade Surveillance Agent. Streams the response using Server-Sent Events (SSE).
     *
     * @name ChatAgentAgentChatPost
     * @summary Chat Agent
     * @request POST:/agent/chat
     */
    chatAgentAgentChatPost: (data, params = {}) =>
      this.request({
        path: `/agent/chat`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),
  };
  reports = {
    /**
     * @description Store a UI-captured chart snapshot for a session+alert.
     *
     * @name UploadChartSnapshotReportsChartSnapshotPost
     * @summary Upload Chart Snapshot
     * @request POST:/reports/chart-snapshot
     */
    uploadChartSnapshotReportsChartSnapshotPost: (data, params = {}) =>
      this.request({
        path: `/reports/chart-snapshot`,
        method: "POST",
        body: data,
        type: ContentType.Json,
        format: "json",
        ...params,
      }),
    /**
     * @description Download a generated report artifact.
     *
     * @name DownloadReportReportsSessionIdReportFilenameGet
     * @summary Download Report
     * @request GET:/reports/{session_id}/{report_filename}
     */
    downloadReportReportsSessionIdReportFilenameGet: (
      sessionId,
      reportFilename,
      params = {},
    ) =>
      this.request({
        path: `/reports/${sessionId}/${reportFilename}`,
        method: "GET",
        format: "json",
        ...params,
      }),
  };
  artifacts = {
    /**
     * @description List artifacts for a session (excluding internal cache/snapshot files).
     *
     * @name ListSessionArtifactsArtifactsSessionIdGet
     * @summary List Session Artifacts
     * @request GET:/artifacts/{session_id}
     */
    listSessionArtifactsArtifactsSessionIdGet: (sessionId, params = {}) =>
      this.request({
        path: `/artifacts/${sessionId}`,
        method: "GET",
        format: "json",
        ...params,
      }),
    /**
     * @description Download artifact by relative path under a session directory.
     *
     * @name DownloadSessionArtifactArtifactsSessionIdDownloadGet
     * @summary Download Session Artifact
     * @request GET:/artifacts/{session_id}/download
     */
    downloadSessionArtifactArtifactsSessionIdDownloadGet: (
      sessionId,
      query,
      params = {},
    ) =>
      this.request({
        path: `/artifacts/${sessionId}/download`,
        method: "GET",
        query: query,
        format: "json",
        ...params,
      }),
  };
}
