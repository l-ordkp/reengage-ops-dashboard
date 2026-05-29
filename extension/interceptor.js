/**
 * Fetch interceptor — runs in the page's MAIN world (bypasses CSP).
 * Detects when DoorDash/UberEats confirms a review has been replied to,
 * then posts the data back to content.js via window.postMessage.
 */
(function () {
  "use strict";

  console.log("[ReEngage Interceptor] Loaded in MAIN world on", window.location.hostname);

  // Walk an arbitrary UE GraphQL response and find any review-shaped object
  // with a populated reply. Handles the list query (data.eaterReviews.reviews)
  // AND the single-review detail query (whatever UE names it) without having
  // to know operation names. Skips merchant-automation config objects (they
  // have replyText:string + automationUUID, not reply.comment + workflowUUID).
  function findUERespondedReviews(json) {
    var found = {};
    var seen = new WeakSet();
    function walk(obj) {
      if (!obj || typeof obj !== "object" || seen.has(obj)) return;
      seen.add(obj);
      if (Array.isArray(obj)) {
        for (var i = 0; i < obj.length; i++) walk(obj[i]);
        return;
      }
      var wf = obj.workflowUUID
        || (obj.order && obj.order.workflowUUID)
        || null;
      if (!wf && obj.uuid && obj.reply && typeof obj.reply === "object") {
        wf = obj.uuid;
      }
      var reply = obj.reply;
      if (wf && reply && typeof reply === "object" &&
          (reply.comment || reply.text || reply.responseText)) {
        found[wf] = {
          workflowUUID: wf,
          userUUID: reply.userUUID || null,
        };
      }
      for (var key in obj) {
        if (Object.prototype.hasOwnProperty.call(obj, key)) walk(obj[key]);
      }
    }
    walk(json);
    var out = [];
    for (var k in found) out.push(found[k]);
    return out;
  }

  var _origFetch = window.fetch;
  window.fetch = function () {
    var args = arguments;
    return _origFetch.apply(this, args).then(function (resp) {
      try {
        var url = typeof args[0] === "string" ? args[0] : (args[0] && args[0].url ? args[0].url : "");
        var init = args[1] || {};
        var method = (init.method || "GET").toUpperCase();

        if (method === "POST" && resp.ok) {
          console.log("[ReEngage Interceptor] POST:", url.slice(0, 120));

          // DoorDash: reviews endpoint
          if (url.indexOf("/consumer_feedback/reviews") !== -1) {
            var clone = resp.clone();
            clone.json().then(function (json) {
              // DoorDash wraps reviews in cxReviewsList
              var reviews = json.cxReviewsList || json.reviews || [];
              if (!Array.isArray(reviews) && json.data) {
                reviews = json.data.cxReviewsList || json.data.reviews || [];
              }
              if (!Array.isArray(reviews)) reviews = [];
              var responded = [];
              for (var i = 0; i < reviews.length; i++) {
                var r = reviews[i];
                if (r.merchantResponded) {
                  // deliveryUuid is nested inside orderReviewDetail
                  var detail = r.orderReviewDetail || {};
                  responded.push({
                    deliveryUuid: detail.deliveryUuid || detail.delivery_uuid || null,
                    cxReviewId: r.cxReviewId || null,
                    storeId: r.storeId || null
                  });
                }
              }
              window.postMessage({
                type: "REENGAGE_PLATFORM_RESPONDED",
                platform: "doordash",
                responded: responded,
                totalReviews: reviews.length
              }, "*");
            }).catch(function () {});
          }

          // UberEats: GraphQL
          if (url.indexOf("/manager/graphql") !== -1) {
            var bodyText = typeof init.body === "string" ? init.body : "";

            // Non-submit UE graphql (list, single-review detail, anything else).
            // Walker is shape-agnostic — finds reviews with replies wherever they
            // sit in the response.
            if (bodyText.indexOf("SubmitReply") === -1) {
              var clone2 = resp.clone();
              clone2.json().then(function (json) {
                var responded = findUERespondedReviews(json);
                if (responded.length > 0) {
                  console.log("[ReEngage Interceptor] Fetch UE graphql scan: found", responded.length, "responded reviews");
                  window.postMessage({
                    type: "REENGAGE_PLATFORM_RESPONDED",
                    platform: "ubereats",
                    responded: responded,
                    totalReviews: responded.length
                  }, "*");
                }
              }).catch(function () {});
            }

            // SubmitReply mutation (fetch path)
            if (bodyText.indexOf("SubmitReply") !== -1) {
              var reqBody2 = {};
              try { reqBody2 = JSON.parse(bodyText); } catch (e) {}
              var vars2 = reqBody2.variables || {};
              var clone3 = resp.clone();
              clone3.json().then(function (json) {
                if (json.data && json.data.submitEaterReviewReply) {
                  var reply = json.data.submitEaterReviewReply;
                  // UE's submitEaterReviewReply.uuid echoes back the review's
                  // workflowUUID rather than minting a distinct reply ID. Only
                  // surface platform_reply_id when it's actually different.
                  var ueReplyId2 = (reply.uuid && reply.uuid !== vars2.workflowUUID) ? reply.uuid : "";
                  var ueCouponId2 = reply.promotion ? (reply.promotion.uuid || "") : "";
                  console.log("[ReEngage Interceptor] Fetch UberEats reply submitted!", {
                    comment: vars2.comment,
                    promotionValue: vars2.promotionValue,
                    workflowUUID: vars2.workflowUUID,
                    platform_reply_id: ueReplyId2,
                    platform_coupon_id: ueCouponId2,
                  });
                  window.postMessage({
                    type: "REENGAGE_REPLY_SUBMITTED",
                    platform: "ubereats",
                    qc: {
                      replied_response: vars2.comment || "",
                      replied_discount: vars2.promotionValue || "NONE",
                      order_id: vars2.workflowUUID || "",
                      confirmed_response: reply.comment || "",
                      confirmed_discount: reply.promotion ? (reply.promotion.formattedValue || reply.promotion.flatValue || "0") : "0",
                      platform_reply_id: ueReplyId2,
                      platform_coupon_id: ueCouponId2,
                    }
                  }, "*");
                }
              }).catch(function () {});
            }
          }
        }
      } catch (e) {}
      return resp;
    });
  };
  // ── Also intercept XMLHttpRequest (DoorDash uses Axios/XHR for reviews) ──
  var _origOpen = XMLHttpRequest.prototype.open;
  var _origSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function (method, url) {
    this._reengageUrl = url || "";
    this._reengageMethod = (method || "GET").toUpperCase();
    return _origOpen.apply(this, arguments);
  };

  XMLHttpRequest.prototype.send = function (body) {
    var self = this;
    var bodyStr = typeof body === "string" ? body : "";

    // DoorDash: reviews endpoint (XHR)
    if (this._reengageMethod === "POST" && this._reengageUrl.indexOf("/consumer_feedback/reviews") !== -1) {
      this.addEventListener("load", function () {
        try {
          var json = JSON.parse(self.responseText);
          var reviews = json.cxReviewsList || json.reviews || [];
          if (!Array.isArray(reviews)) reviews = [];
          var responded = [];
          for (var i = 0; i < reviews.length; i++) {
            var r = reviews[i];
            if (r.merchantResponded) {
              var detail = r.orderReviewDetail || {};
              responded.push({
                deliveryUuid: detail.deliveryUuid || detail.delivery_uuid || null,
                cxReviewId: r.cxReviewId || null,
                storeId: r.storeId || null
              });
            }
          }
          console.log("[ReEngage Interceptor] XHR DoorDash reviews:", reviews.length, "responded:", responded.length);
          window.postMessage({
            type: "REENGAGE_PLATFORM_RESPONDED",
            platform: "doordash",
            responded: responded,
            totalReviews: reviews.length
          }, "*");
        } catch (e) {}
      });
    }

    // UberEats: GraphQL endpoint (XHR)
    if (this._reengageMethod === "POST" && this._reengageUrl.indexOf("/manager/graphql") !== -1) {
      this.addEventListener("load", function () {
        try {
          var json = JSON.parse(self.responseText);

          // Case 1: Any UE graphql response that isn't a SubmitReply — walk
          // it to find review objects with replies, wherever they nest.
          // Catches both the list query and the single-review detail query
          // without depending on UE's operation naming.
          var hasSubmitReply = json && json.data && json.data.submitEaterReviewReply;
          if (!hasSubmitReply) {
            var responded = findUERespondedReviews(json);
            if (responded.length > 0) {
              console.log("[ReEngage Interceptor] XHR UE graphql scan: found", responded.length, "responded reviews");
              window.postMessage({
                type: "REENGAGE_PLATFORM_RESPONDED",
                platform: "ubereats",
                responded: responded,
                totalReviews: responded.length
              }, "*");
            }
          }

          // Case 2: SubmitReply mutation response — reply was just posted
          if (json.data && json.data.submitEaterReviewReply) {
            var reply = json.data.submitEaterReviewReply;
            // Parse the request body to get what operator actually submitted
            var reqBody = {};
            try { reqBody = JSON.parse(bodyStr); } catch (e) {}
            var vars = reqBody.variables || {};

            // UE's submitEaterReviewReply.uuid echoes back the review's
            // workflowUUID rather than minting a distinct reply ID. Only
            // surface platform_reply_id when it's actually different.
            var ueReplyId = (reply.uuid && reply.uuid !== vars.workflowUUID) ? reply.uuid : "";
            var ueCouponId = reply.promotion ? (reply.promotion.uuid || "") : "";

            console.log("[ReEngage Interceptor] UberEats reply submitted!", {
              comment: vars.comment,
              promotionValue: vars.promotionValue,
              workflowUUID: vars.workflowUUID,
              platform_reply_id: ueReplyId,
              platform_coupon_id: ueCouponId,
            });

            window.postMessage({
              type: "REENGAGE_REPLY_SUBMITTED",
              platform: "ubereats",
              qc: {
                replied_response: vars.comment || "",
                replied_discount: vars.promotionValue || "NONE",
                order_id: vars.workflowUUID || "",
                confirmed_response: reply.comment || "",
                confirmed_discount: reply.promotion ? (reply.promotion.formattedValue || reply.promotion.flatValue || "0") : "0",
                platform_reply_id: ueReplyId,
                platform_coupon_id: ueCouponId,
              }
            }, "*");
          }
        } catch (e) {}
      });
    }

    // DoorDash: detect reply submission (respond to review endpoint)
    if (this._reengageMethod === "POST" && this._reengageUrl.indexOf("/consumer_feedback/send_response") !== -1) {
      // Parse request body for QC
      var ddReqBody = {};
      try { ddReqBody = JSON.parse(bodyStr); } catch (e) {}
      var ddContent = ddReqBody.messageContent || {};

      this.addEventListener("load", function () {
        if (self.status >= 200 && self.status < 300) {
          // Parse response body for platform-issued IDs (messageId for the reply,
          // campaignId for the coupon — campaignId is null when no coupon attached).
          var ddResp = {};
          try { ddResp = JSON.parse(self.responseText); } catch (e) {}
          var ddResult = ddResp.result || {};
          var platformReplyId = ddResult.messageId || "";
          var platformCouponId = ddResp.campaignId || "";

          console.log("[ReEngage Interceptor] DoorDash reply submitted!", {
            mx_response: ddContent.mx_response,
            promo_value: ddContent.promo_value,
            complaintId: ddReqBody.complaintId,
            platform_reply_id: platformReplyId,
            platform_coupon_id: platformCouponId,
          });
          window.postMessage({
            type: "REENGAGE_REPLY_SUBMITTED",
            platform: "doordash",
            qc: {
              replied_response: ddContent.mx_response || "",
              replied_discount: String(ddContent.promo_value || 0),
              order_id: ddReqBody.complaintId || "",
              platform_reply_id: platformReplyId,
              platform_coupon_id: platformCouponId,
            }
          }, "*");
        }
      });
    }

    return _origSend.apply(this, arguments);
  };
})();
