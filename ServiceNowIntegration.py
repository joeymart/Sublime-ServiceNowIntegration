import sublime, sublime_plugin, urllib2, base64, json

# Define endpoint (servicenow)
# Get a script include from that endpoint(open by name with cmd-shift-P?)
# Post to servicenow (post script to endpoint custom processor?)
class NowOpenScriptIncludeCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        self.broker = NowScriptIncludeBroker(self.view)
        self.broker.openScriptInclude()

class NowPushScriptIncludeCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        print("sys_id setting? [%s]" % self.view.settings().get("sys_id"))
        self.broker = NowScriptIncludeBroker(self.view)
        self.broker.pushScriptInclude()

    def is_enabled(self):
        return len(self.view.name()) > 0

class NowScriptIncludeBroker:
    def __init__(self, view):
        self.view = view
        self.now = ServiceNowApiCall(self.view.settings().get("user_password"))
    
    def openScriptInclude(self):
        if self.now.hasPassword():
            self.requestScriptInclude(self.onScriptIncludeChosenOpen)
        else:
            self.requestPassword(self.openScriptInclude)

    def pushScriptInclude(self):
        if self.now.hasPassword():
            self.updateScriptInclude()
        else:
            self.requestPassword(self.pushScriptInclude)

    def updateScriptInclude(self):
        # Try to get script include by the name of the view (should work unless user changed)
        includeByName = self.now.getScriptIncludeByName(self.view.name())
        if len(includeByName) <= 0:
            # We don't have the include, ask user for it
            self.requestScriptInclude(self.onScriptIncludeChosenPush)
        else:
            # We have a script include by name, update that
            self.scriptIncludes = includeByName
            self.onScriptIncludeChosenPush(0)

    def requestPassword(self, callback):
        self.afterGotPasswordCallback = callback
        self.view.window().show_input_panel("Password: ", "", self.gotPasswordInput, None, None)

    def gotPasswordInput(self, text):
        pw = str(text)
        if (len(pw) > 0):
            self.view.settings().set("user_password", pw)
            self.now.setPassword(pw)
            self.afterGotPasswordCallback()
    
    def requestScriptInclude(self, callback):
        self.scriptIncludes = self.now.getScriptIncludes()
        messages = []
        for si in self.scriptIncludes:
            messages.append(si['name'])

        self.show_quick_panel(messages, self.view.window(), callback)

    def show_quick_panel(self, messages, window, callback):
        window.show_quick_panel(messages, callback, sublime.MONOSPACE_FONT)

    def onScriptIncludeChosenOpen(self, picked):
        # Get script for selected script include (makes a remote call)
        if picked < 0:
            return

        print "User picked index [%d] of [%d]: %s" % (picked, len(self.scriptIncludes), self.scriptIncludes[picked])
        script = self.scriptIncludes[picked]
        result = self.now.getScriptIncludeById(script['sys_id'])

        # Open script as a new file
        newView = self.view.window().new_file()
        newView.set_name(script['name'])
        edit = newView.begin_edit()
        newView.insert(edit, 0, result['script'])
        newView.end_edit(edit)
        newView.set_syntax_file("Packages/JavaScript/JavaScript.tmLanguage")
        newView.settings().set("user_password", self.now.password)
        newView.settings().set("sys_id", script["sys_id"])

    def onScriptIncludeChosenPush(self, picked):
        if picked < 0:
            return

        script = self.scriptIncludes[picked]
        #result = self.now.getScriptIncludeById(script['sys_id'])
        content = self.view.substr(sublime.Region(0, self.view.size()))
        self.now.updateScriptInclude(script['sys_id'], content)

class ServiceNowApiCall():
    def __init__(self, password):
        settings = sublime.load_settings("ServiceNowIntegration.sublime-settings")
        self.username = settings.get("username", "admin")
        self.baseUrl = settings.get("base_url", 'http://localhost:8080/')
        self.apiSuffix = settings.get("api_suffix", 'api/now/table/')
        self.headers = {"Accept": "application/json"}
        self.password = password

    def hasPassword(self):
        return self.password != None

    def setPassword(self, password):
        self.password = password

    def getScriptIncludes(self):
        return self.getJson("sys_script_include?sysparm_fields=name,sys_id&sysparm_query=ORDERBYname")

    def getScriptIncludeById(self, sysId):
        return self.getJson("sys_script_include/%s" % sysId)

    def getScriptIncludeByName(self, name):
        return self.getJson("sys_script_include?sysparm_fields=name,sys_id&sysparm_query=name=%s&sysparm_limit=1" % name)

    def updateScriptInclude(self, sysId, script):
        print "Updating sys_script_include.[%s] to script of length[%d]" % (sysId, len(script))
        #jsonifiedScript = '"%s"' % script
        jsonPayload = json.dumps({"script": script})
        self.putJson("sys_script_include/%s" % sysId, jsonPayload)

    def getBasicAuthString(self):
        base64string = base64.encodestring('%s:%s' % (self.username, self.password))[:-1]
        return "Basic %s" % base64string

    def getRequest(self, urlSuffix):
        # Build request with basic auth
        url = self.baseUrl + self.apiSuffix + urlSuffix
        print "getRequest url=[%s]" % url
        req = urllib2.Request(url, headers=self.headers)
        req.add_header("Authorization", self.getBasicAuthString())
        return req

    def putJson(self, urlSuffix, jsonPayload):
        try:
            print "putJson urlSuffix=[%s]" % urlSuffix
            opener = urllib2.build_opener(urllib2.HTTPHandler)
            url = self.baseUrl + self.apiSuffix + urlSuffix
            sublime.status_message("Pushing to %s..." % url)
            print "Making PutRequest to [%s]" % url
            req = PutRequest(url, headers=self.headers, data=jsonPayload)
            req.add_header("Authorization", self.getBasicAuthString())
            req.add_header("Content-Type", "application/json")
            res = opener.open(req)
            data = res.read()
            return data
        except urllib2.HTTPError, e:
            err = 'HTTPError = ' + str(e.code)
            if e.code in (400,401):
                self.password = None
                
        except urllib2.URLError, e:
            err = 'URLError = ' + str(e.reason)
        except Exception, e:
            err = 'generic exception: ' + str(e)
        
        sublime.error_message(err)

    def getJson(self, urlSuffix):
        try:
            sublime.status_message("Querying %s..." % urlSuffix)
            print "urlSuffix=[%s]" % urlSuffix
            req = self.getRequest(urlSuffix);

            res = urllib2.urlopen(req)
            data = res.read()
            names = json.loads(data)
            return names.get('result')
 
        except urllib2.HTTPError, e:
            err = 'HTTPError = ' + str(e.code)
            if e.code in (400,401):
                self.password = None

        except urllib2.URLError, e:
            err = 'URLError = ' + str(e.reason)
        except Exception, e:
            err = 'generic exception: ' + str(e)
        
        sublime.error_message(err)
        return []

class PutRequest(urllib2.Request):
  def __init__(self, *args, **kwargs):
    urllib2.Request.__init__(self, *args, **kwargs)

  def get_method(self):
    return "PUT"